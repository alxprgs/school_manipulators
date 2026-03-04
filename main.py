import asyncio
import random
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Dict, Optional
import time

# ====================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ======================
devices: Dict[str, tuple] = {}           # full_id -> (ip, port)
lamps: Dict[str, tuple] = {}             # только лампы
manipulators: Dict[str, tuple] = {}      # только манипуляторы
remotes: Dict[str, tuple] = {}           # только пульты

remote_states: Dict[str, dict] = {}      # состояние пульта
remote_to_mp: Dict[str, str] = {}        # какой манипулятор сейчас выбран пультом
remote_to_layer: Dict[str, int] = {}     # текущий слой 0-2
manip_pos: Dict[str, Dict[int, int]] = {} # текущее положение серв (для velocity)

list_manips: list = []                   # список всех манипуляторов для переключения

lamp_states: Dict[str, str] = {}
short_to_full: Dict[str, str] = {}
last_seen: Dict[str, float] = {}

disco_active = False
disco_task: Optional[asyncio.Task] = None
original_states: Dict[str, Dict[str, int]] = {}


# ====================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======================
def parse_lamp_state(state_str: str) -> Dict[str, int]:
    parts = state_str.split(':')
    state = {}
    for part in parts:
        if part and part[0] in ('R', 'Y', 'G', 'B') and len(part) >= 2:
            color = part[0]
            value = int(part[1])
            state[color] = value
    return state


def parse_remote_state(state_str: str) -> dict:
    parts = state_str.split(':')
    state = {}
    for part in parts:
        if not part:
            continue
        if part[0] == 'E' and len(part) >= 2:
            state['emergency'] = int(part[1])
        elif part[0] == 'R' and len(part) >= 2:
            state['red'] = int(part[1])
        elif part[0] == 'Y' and len(part) >= 2:
            state['yellow'] = int(part[1])
        elif part[0] == 'G' and len(part) >= 2:
            state['green'] = int(part[1])
        elif part.startswith('JX'):
            state['joy_x'] = int(part[2:])
        elif part.startswith('JY'):
            state['joy_y'] = int(part[2:])
    return state


async def send_command(device_id: str, command: str) -> bool:
    if device_id not in devices:
        return False
    addr = devices[device_id]
    try:
        app.state.udp_transport.sendto(command.encode(), addr)
        return True
    except Exception as e:
        print(f"[!] Ошибка отправки {device_id}: {e}")
        await remove_device(device_id)
        return False


async def remove_device(device_id: str):
    short = device_id.replace("ID:", "")
    short_to_full.pop(short, None)
    devices.pop(device_id, None)
    last_seen.pop(device_id, None)
    lamps.pop(device_id, None)
    remotes.pop(device_id, None)
    manipulators.pop(device_id, None)
    lamp_states.pop(device_id, None)
    remote_states.pop(device_id, None)
    remote_to_mp.pop(device_id, None)
    remote_to_layer.pop(device_id, None)
    manip_pos.pop(device_id, None)
    if device_id in list_manips:
        list_manips.remove(device_id)
    original_states.pop(device_id, None)
    print(f"[!] Устройство {device_id} удалено")


# ====================== ФОНОВЫЕ ЗАДАЧИ ======================
async def cleanup_dead_connections():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        dead = [did for did, last in last_seen.items() if now - last > 60]
        for did in dead:
            print(f"[!] Таймаут {did}, удаляем")
            await remove_device(did)


async def manipulator_control_loop():
    while True:
        await asyncio.sleep(0.05)  # 50 Гц
        for rid, state in list(remote_states.items()):
            if state.get('emergency', 1) == 0:          # авария — ничего не делаем
                continue
            mp = remote_to_mp.get(rid)
            if not mp or mp not in manipulators:
                continue

            layer = remote_to_layer.get(rid, 0)
            jx = state.get('joy_x', 512) - 512
            jy = state.get('joy_y', 512) - 512

            if abs(jx) <= 40 and abs(jy) <= 40:         # deadzone — фиксируем позицию
                continue

            # Скорость пропорциональна отклонению джойстика
            delta_x = int(jx / 512.0 * 45)   # подбери под себя
            delta_y = int(jy / 512.0 * 45)

            if delta_x == 0 and delta_y == 0:
                continue

            # Какие моторы в текущем слое
            motors = [[1, 2], [3, 4], [5, 6]]
            m1, m2 = motors[layer]

            p1 = manip_pos[mp][m1] + delta_x
            p2 = manip_pos[mp][m2] + delta_y
            p1 = max(0, min(4095, p1))
            p2 = max(0, min(4095, p2))

            await send_command(mp, f"M{m1}:{p1}")
            await send_command(mp, f"M{m2}:{p2}")

            manip_pos[mp][m1] = p1
            manip_pos[mp][m2] = p2


def update_lcd_for_remote(rid: str):
    mp = remote_to_mp.get(rid, "Нет")
    layer = remote_to_layer.get(rid, 0)
    short_mp = mp.split(':')[-1] if mp != "Нет" else "Нет"
    asyncio.create_task(send_command(rid, f"LCD:2:MP:{short_mp}"))
    asyncio.create_task(send_command(rid, f"LCD:3:Layer:{layer}"))


def handle_switch_mp(addr):
    """Переключение манипулятора по жёлтой кнопке"""
    for rid, raddr in list(devices.items()):
        if raddr == addr and rid in remotes:
            if not list_manips:
                return
            current = remote_to_mp.get(rid)
            if current not in list_manips or current is None:
                idx = 0
            else:
                idx = list_manips.index(current)
            new_idx = (idx + 1) % len(list_manips)
            new_mp = list_manips[new_idx]
            remote_to_mp[rid] = new_mp
            if rid not in remote_to_layer:
                remote_to_layer[rid] = 0
            update_lcd_for_remote(rid)
            return


def handle_layer_change(addr, delta: int):
    """Смена слоя красной/зелёной кнопкой"""
    for rid, raddr in list(devices.items()):
        if raddr == addr and rid in remotes:
            layer = remote_to_layer.get(rid, 0)
            layer = (layer + delta) % 3
            remote_to_layer[rid] = layer
            update_lcd_for_remote(rid)
            return


# ====================== LIFESPAN ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPProtocol(), local_addr=('0.0.0.0', 8888))
    app.state.udp_transport = transport
    app.state.udp_protocol = protocol

    asyncio.create_task(cleanup_dead_connections())
    asyncio.create_task(manipulator_control_loop())

    print("[!] UDP сервер запущен на порту 8888")
    yield
    transport.close()


app = FastAPI(lifespan=lifespan, docs_url="/docs", openapi_url="/openapi")


# ====================== UDP ПРОТОКОЛ ======================
class UDPProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        msg = data.decode().strip()
        print(f"[<-] От {addr}: {msg}")

        # 1. Регистрация
        if msg.startswith("ID:"):
            full_id = msg
            devices[full_id] = addr
            last_seen[full_id] = time.time()

            if ":DL:" in full_id:
                lamps[full_id] = addr
                print(f"[+] Лампа: {full_id}")
            elif ":MP:" in full_id:
                manipulators[full_id] = addr
                list_manips.append(full_id)
                if full_id not in manip_pos:
                    manip_pos[full_id] = {i: 2048 for i in range(1, 7)}
                print(f"[+] Манипулятор: {full_id}")
            elif ":PT:" in full_id:
                remotes[full_id] = addr
                # Автоматически назначаем первый манипулятор
                if list_manips and full_id not in remote_to_mp:
                    remote_to_mp[full_id] = list_manips[0]
                    remote_to_layer[full_id] = 0
                    update_lcd_for_remote(full_id)
                print(f"[+] Пульт: {full_id}")
            else:
                print(f"[!] Неизвестный тип: {full_id}")
                return

            short = full_id.replace("ID:", "")
            short_to_full[short] = full_id

        # 2. Статус пульта / лампы
        elif msg.startswith("T"):
            try:
                parts = msg.split(':')
                if len(parts) < 3:
                    return
                short_key = f"{parts[0]}:{parts[1]}:{parts[2]}"
                full_id = short_to_full.get(short_key)
                if not full_id:
                    return

                last_seen[full_id] = time.time()

                if full_id in lamps:
                    lamp_states[full_id] = msg
                elif full_id in remotes:
                    remote_states[full_id] = parse_remote_state(msg)
                # для манипулятора статус не обязателен
            except:
                pass

        # 3. Специальные команды от пульта
        elif msg == "SWITCH_MP":
            handle_switch_mp(addr)
        elif msg == "LAYER_PLUS":
            handle_layer_change(addr, 1)
        elif msg == "LAYER_MINUS":
            handle_layer_change(addr, -1)

        # 4. Остальные сообщения — просто обновляем last_seen
        else:
            for fid, faddr in devices.items():
                if faddr == addr:
                    last_seen[fid] = time.time()
                    break

    def error_received(self, exc):
        print(f"[!] UDP ошибка: {exc}")


# ====================== ЭНДПОИНТЫ ======================
class Command(BaseModel):
    device_id: str
    color: str
    status: int


class MotorCommand(BaseModel):
    device_id: str
    motor_id: int
    position: int


@app.get("/devices")
async def get_devices():
    return {"online": list(devices.keys())}


@app.get("/lamps")
async def get_lamps():
    return {"online": list(lamps.keys()), "states": lamp_states}


@app.get("/remotes")
async def get_remotes():
    return {"online": list(remotes.keys()), "states": remote_states}


@app.get("/remote/{device_id}")
async def get_remote_state(device_id: str):
    if device_id not in remotes:
        raise HTTPException(404, "Remote not found")
    return remote_states.get(device_id, {})


@app.post("/control/lamp")
async def control_lamp(cmd: Command):
    if cmd.device_id not in lamps:
        raise HTTPException(404, "Lamp not found")
    if disco_active:
        raise HTTPException(409, "Disco mode active")
    success = await send_command(cmd.device_id, f"{cmd.color}{cmd.status}")
    if not success:
        raise HTTPException(500, "Send failed")
    return {"status": "sent"}


@app.post("/control/remote")
async def control_remote(cmd: Command):
    if cmd.device_id not in remotes:
        raise HTTPException(404, "Remote not found")
    success = await send_command(cmd.device_id, f"{cmd.color}{cmd.status}")
    if not success:
        raise HTTPException(500, "Send failed")
    return {"status": "sent"}


@app.post("/control/motor")
async def control_motor(cmd: MotorCommand):
    """Прямое управление сервоприводом (для отладки)"""
    if cmd.device_id not in manipulators:
        raise HTTPException(404, "Manipulator not found")
    command = f"M{cmd.motor_id}:{cmd.position}"
    success = await send_command(cmd.device_id, command)
    if not success:
        raise HTTPException(500, "Send failed")
    return {"status": "sent", "command": command}


@app.get("/broadcast/on")
async def broadcast_on():
    if not lamps:
        raise HTTPException(400, "No lamps")
    for did in list(lamps.keys()):
        await send_command(did, "1111")
    return {"message": "Broadcast ON", "count": len(lamps)}


@app.get("/broadcast/off")
async def broadcast_off():
    if not lamps:
        raise HTTPException(400, "No lamps")
    for did in list(lamps.keys()):
        await send_command(did, "0000")
    return {"message": "Broadcast OFF", "count": len(lamps)}


# ====================== ДИСКОТЕКА ======================
@app.get("/disco/start")
async def disco_start():
    global disco_active, disco_task, original_states
    if disco_active:
        raise HTTPException(400, "Disco already active")
    if not lamps:
        raise HTTPException(400, "No lamps")

    for did in lamps:
        state_str = lamp_states.get(did)
        parsed = parse_lamp_state(state_str) if state_str else {}
        original_states[did] = parsed or {'R': 0, 'Y': 0, 'G': 0, 'B': 0}

    disco_active = True
    disco_task = asyncio.create_task(disco_loop())
    return {"message": "Disco started", "devices": len(original_states)}


@app.get("/disco/stop")
async def disco_stop():
    global disco_active, disco_task
    if not disco_active:
        raise HTTPException(400, "Disco not active")

    disco_active = False
    if disco_task:
        disco_task.cancel()
        try:
            await disco_task
        except asyncio.CancelledError:
            pass
        disco_task = None

    restored = 0
    for did, states in original_states.items():
        if did in lamps:
            for color, status in states.items():
                await send_command(did, f"{color}{status}")
            restored += 1
    original_states.clear()
    return {"message": "Disco stopped", "restored": restored}


async def disco_loop(interval: float = 0.3):
    colors_on = ['R', 'Y', 'G', 'B']
    for color in colors_on:
        if not disco_active: return
        for did in list(lamps.keys()):
            await send_command(did, f"{color}1")
        await asyncio.sleep(interval)

    await asyncio.sleep(interval)

    colors_off = ['B', 'G', 'Y', 'R']
    for color in colors_off:
        if not disco_active: return
        for did in list(lamps.keys()):
            await send_command(did, f"{color}0")
        await asyncio.sleep(interval)

    while disco_active:
        for did in list(lamps.keys()):
            color = random.choice(['R', 'Y', 'G', 'B'])
            status = random.randint(0, 1)
            await send_command(did, f"{color}{status}")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)