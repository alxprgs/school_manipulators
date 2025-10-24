from server import app, manager
from fastapi import WebSocket, WebSocketDisconnect
from server.core.functions.auth import check_code
import time
import traceback
import asyncio
import random

emergency: list[str] = []
party_tasks: dict[str, asyncio.Task] = {}

PARTY_COLORS = ["red", "orange", "green", "blue"]


async def party_mode(table: str):
    try:
        while table in emergency:
            await manager.set_remote_controller_color(table, random.choice(PARTY_COLORS), True)
            await manager.set_light_stand_color(table, 1, random.choice(PARTY_COLORS), True)
            await manager.set_light_stand_color(table, 2, random.choice(PARTY_COLORS), True)
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        await manager.set_table_colors(table, "green", True)
        print(f"[i] Party mode stopped for {table}")


@app.websocket("/ws/{table}/{device}/{id}")
async def ws_device(websocket: WebSocket, table: str, device: str, id: int = 0):
    key = f"{table}.{device}_{id}"
    await manager.connect(table, device, id, websocket)
    authorized = False

    try:
        while True:
            msg = await websocket.receive_json()
            if not msg:
                break

            manager.last_seen[key] = time.time()

            action = msg.get("action")

            if not authorized:
                if action != "auth":
                    await websocket.send_json({"status": False, "type": "error", "msg": "unauthorized"})
                    continue

                auth_code = msg.get("auth_code")
                auth = await check_code(
                    table=table,
                    device_name=f"{device}_{id}",
                    device_code=auth_code,
                    autoreload=False
                )

                if not auth:
                    await websocket.send_json({"status": False, "type": "error", "msg": "Wrong device code"})
                    await websocket.close(code=4001)
                    await manager.disconnect(table, device, id)
                    return 

                authorized = True
                await websocket.send_json({"status": True, "type": "info", "msg": "Success authorized"})
                continue

            if action == "ping":
                await manager.send_to(key, {"status": True, "type": "info", "msg": "Pong"})
                continue

            if device.lower().startswith("remote_controller"):
                if action == "joystick":
                    if table in emergency:
                        await manager.send_to(key, {"status": False, "type": "error", "msg": "The emergency button is enabled"})
                        continue
                    payload = msg.get("payload", {})
                    manipulator = payload.get("manipulator_id")
                    x = payload.get("x")
                    y = payload.get("y")
                    if manipulator is None or x is None or y is None:
                        await manager.send_to(key, {"status": False, "type": "error", "msg": "Invalid joystick payload"})
                        continue
                    await manager.send_to(f"{table}.light_stand_{manipulator}", {
                        "action": "action_manipulator_xy",
                        "payload": {"x": x, "y": y}
                    })

                elif action == "emergency_button":
                    payload = msg.get("payload", {})
                    event_type = payload.get("type")

                    if event_type == "emergency":
                        if table not in emergency:
                            emergency.append(table)
                        await manager.send_to(key, {
                            "status": True,
                            "type": "info",
                            "msg": "Successful emergency stop"
                        })
                        await manager.set_table_colors(table, "red", True)

                    else:
                        if table in emergency:
                            emergency.remove(table)
                        task = party_tasks.pop(table, None)
                        if task:
                            task.cancel()
                        await manager.send_to(key, {
                            "status": True,
                            "type": "info",
                            "msg": "Emergency stop released"
                        })
                        await manager.set_table_colors(table, "green", True)

                elif action == "green_button":
                    manipulator = msg.get("payload", {}).get("manipulator_id", 1)
                    await manager.send_to(f"{table}.light_stand_{manipulator}", {
                        "action": "action_manipulator_catch",
                        "payload": {"action": "compression"}
                    })

                elif action == "red_button":
                    manipulator = msg.get("payload", {}).get("manipulator_id", 1)
                    await manager.send_to(f"{table}.light_stand_{manipulator}", {
                        "action": "action_manipulator_catch",
                        "payload": {"action": "ras_compression"}
                    })

                else:
                    await manager.send_to(key, {"status": False, "type": "error", "msg": "Unknown action"})

            elif device.lower().startswith("button"):
                if action != "button_press":
                    await manager.send_to(key, {"status": False, "type": "error", "msg": "Unsupported action"})
                    continue

                if table not in emergency:
                    await manager.send_to(key, {"status": False, "type": "error", "msg": "The emergency button is not enabled"})
                    continue

                if table in party_tasks:
                    task = party_tasks.pop(table, None)
                    if task:
                        task.cancel()
                    await manager.set_table_colors(table, "green", True)
                    await manager.send_to(key, {
                        "status": True,
                        "type": "info",
                        "msg": "Party mode stopped"
                    })
                else:
                    task = asyncio.create_task(party_mode(table))
                    party_tasks[table] = task
                    await manager.send_to(key, {
                        "status": True,
                        "type": "info",
                        "msg": "Party mode started"
                    })

            else:
                await manager.send_to(key, {"status": False, "type": "error", "msg": "Unknown device type"})

    except WebSocketDisconnect:
        await manager.disconnect(table, device, id)
        if device.lower().startswith("button"):
            task = party_tasks.pop(table, None)
            if task:
                task.cancel()
                await manager.set_table_colors(table, "green", True)
                print(f"[i] Party mode task cancelled (button disconnect) for {table}")
    except Exception as e:
        print(f"[!] Error in {key}: {e}\n{traceback.format_exc()}")
        await manager.disconnect(table, device, id)
