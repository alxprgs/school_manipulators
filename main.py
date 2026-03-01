import asyncio
import random
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Dict, Optional

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    server = await asyncio.start_server(handle_tcp_client, '0.0.0.0', 8888)
    server_task = loop.create_task(server.serve_forever())
    print("[!] TCP Сервер запущен на порту 8888")
    yield
    server_task.cancel()
    await server.wait_closed()

app = FastAPI(lifespan=lifespan)

# Хранилище активных соединений и состояний
devices: Dict[str, asyncio.StreamWriter] = {}
device_states: Dict[str, str] = {}

# Переменные диско-режима
disco_active = False
disco_task: Optional[asyncio.Task] = None
original_states: Dict[str, Dict[str, int]] = {}  # {device_id: {"R":0/1, "Y":0/1, "G":0/1, "B":0/1}}

class Command(BaseModel):
    device_id: str
    color: str = None
    status: int  # 1 или 0

# ---------- Вспомогательные функции ----------
def parse_state(state_str: str) -> Dict[str, int]:
    """Из строки 'T1:DL:N1:AC:R0:Y0:G0:B0' достаёт {'R':0, 'Y':0, 'G':0, 'B':0}"""
    parts = state_str.split(':')
    state = {}
    for part in parts:
        if part and part[0] in ('R', 'Y', 'G', 'B') and len(part) >= 2:
            color = part[0]
            value = int(part[1])
            state[color] = value
    return state

async def set_color(device_id: str, color: str, status: int) -> bool:
    """Отправляет команду изменения цвета конкретному устройству."""
    if device_id not in devices:
        return False
    msg = f"CS:S:C{color}:S{status}\n"
    writer = devices[device_id]
    try:
        writer.write(msg.encode())
        await writer.drain()
        return True
    except Exception as e:
        print(f"[!] Ошибка отправки {device_id}: {e}")
        return False

async def restore_device(device_id: str):
    """Восстанавливает исходное состояние устройства (из original_states)."""
    if device_id not in original_states:
        return
    states = original_states[device_id]
    for color, status in states.items():
        await set_color(device_id, color, status)

# ---------- Диско-цикл ----------
async def disco_loop(interval: float = 0.5):
    global disco_active
    while disco_active:
        # Отправляем случайные цвета всем подключённым устройствам
        for device_id in list(devices.keys()):
            for color in ['R', 'Y', 'G', 'B']:
                status = random.randint(0, 1)
                await set_color(device_id, color, status)
        await asyncio.sleep(interval)

# ---------- Обработка TCP-клиентов ----------
async def handle_tcp_client(reader, writer):
    addr = writer.get_extra_info('peername')
    device_id = None
    try:
        while True:
            data = await reader.read(1024)
            if not data:
                break
            raw_messages = data.decode().split('\n')
            for message in raw_messages:
                msg = message.strip()
                if not msg:
                    continue
                print(f"[<-] От {addr}: {msg}")

                if msg.startswith("ID:"):
                    device_id = msg.replace("ID:", "")
                    devices[device_id] = writer
                    print(f"[!] Зарегистрирован: {device_id}")

                elif ":BS" in msg or ":AC" in msg or ":C" in msg:
                    parts = msg.split(":")
                    if len(parts) >= 3:
                        state_key = ":".join(parts[:3])
                        device_states[state_key] = msg
    except Exception as e:
        print(f"[!] Ошибка TCP: {e}")
    finally:
        if device_id:
            if device_id in devices:
                del devices[device_id]
            # Если устройство участвовало в диско, удаляем его из сохранённых состояний
            if device_id in original_states:
                del original_states[device_id]
        writer.close()
        await writer.wait_closed()

# ---------- Эндпоинты ----------
@app.get("/devices")
async def get_devices():
    return {"online": list(devices.keys()), "states": device_states}

@app.post("/control/lamp")
async def control_lamp(cmd: Command):
    if disco_active:
        raise HTTPException(status_code=409, detail="Disco mode is active, manual control disabled")
    if cmd.device_id not in devices:
        raise HTTPException(status_code=404, detail="Устройство не в сети")
    msg = f"CS:S:C{cmd.color}:S{cmd.status}\n"
    writer = devices[cmd.device_id]
    writer.write(msg.encode())
    await writer.drain()
    return {"status": "sent", "command": msg.strip()}

@app.post("/disco/start")
async def disco_start():
    global disco_active, disco_task, original_states
    if disco_active:
        raise HTTPException(status_code=400, detail="Disco mode already active")
    if not devices:
        raise HTTPException(status_code=400, detail="No devices connected")

    # Сохраняем текущие состояния всех подключённых устройств
    saved_count = 0
    for device_id in devices:
        state_str = device_states.get(device_id)
        if state_str:
            parsed = parse_state(state_str)
            if parsed:
                original_states[device_id] = parsed
            else:
                # Если не удалось распарсить (например, нет информации о цветах)
                original_states[device_id] = {'R': 0, 'Y': 0, 'G': 0, 'B': 0}
        else:
            # Нет статуса – считаем всё выключенным
            original_states[device_id] = {'R': 0, 'Y': 0, 'G': 0, 'B': 0}
        saved_count += 1

    disco_active = True
    disco_task = asyncio.create_task(disco_loop())
    return {"message": "Disco mode started", "devices_count": saved_count}

@app.post("/disco/stop")
async def disco_stop():
    global disco_active, disco_task, original_states
    if not disco_active:
        raise HTTPException(status_code=400, detail="Disco mode not active")

    disco_active = False
    if disco_task:
        disco_task.cancel()
        try:
            await disco_task
        except asyncio.CancelledError:
            pass
        disco_task = None

    # Восстанавливаем исходные состояния
    restored_count = 0
    for device_id, states in original_states.items():
        if device_id in devices:  # проверяем, не отключилось ли устройство
            for color, status in states.items():
                await set_color(device_id, color, status)
            restored_count += 1
    original_states.clear()

    return {"message": "Disco mode stopped", "devices_restored": restored_count}

# ---------- Запуск Uvicorn при прямом выполнении скрипта ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)