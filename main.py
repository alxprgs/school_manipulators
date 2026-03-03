import asyncio
import random
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager
from pydantic import BaseModel
from typing import Dict, Optional, Tuple
import time

@asynccontextmanager
async def lifespan(app: FastAPI):
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: UDPProtocol(),
        local_addr=('0.0.0.0', 8888)
    )
    app.state.udp_transport = transport
    app.state.udp_protocol = protocol

    cleanup_task = loop.create_task(cleanup_dead_connections())
    print("[!] UDP сервер запущен на порту 8888")
    yield
    cleanup_task.cancel()
    transport.close()

app = FastAPI(lifespan=lifespan, docs_url="/docs", openapi_url="/openapi")

# Хранилища
devices: Dict[str, Tuple[str, int]] = {}          # полный ID -> (ip, port)
short_to_full: Dict[str, str] = {}                 # "T2:DL:N2" -> полный ID
device_states: Dict[str, str] = {}                 # полный ID -> последний статус
last_seen: Dict[str, float] = {}                   # полный ID -> время

disco_active = False
disco_task: Optional[asyncio.Task] = None
original_states: Dict[str, Dict[str, int]] = {}

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
    """Удаляет устройство из всех словарей."""
    if device_id in devices:
        # Удаляем из short_to_full
        short = device_id.replace("ID:", "")
        short_to_full.pop(short, None)
        # Удаляем из остальных словарей
        devices.pop(device_id, None)
        device_states.pop(device_id, None)
        last_seen.pop(device_id, None)
        original_states.pop(device_id, None)
        print(f"[!] Устройство {device_id} удалено")

async def restore_device(device_id: str):
    if device_id not in original_states:
        return
    states = original_states[device_id]
    for color, status in states.items():
        await send_command(device_id, f"{color}{status}")

# ---------- Фоновая проверка ----------
async def cleanup_dead_connections():
    while True:
        await asyncio.sleep(30)
        now = time.time()
        dead = [did for did, last in last_seen.items() if now - last > 60]
        for did in dead:
            print(f"[!] Таймаут {did}, удаляем")
            await remove_device(did)

# ---------- UDP протокол ----------
class UDPProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        msg = data.decode().strip()
        print(f"[<-] От {addr}: {msg}")

        # 1. Регистрация (начинается с "ID:")
        if msg.startswith("ID:"):
            full_id = msg
            if full_id in devices:
                print(f"[!] Повторная регистрация {full_id}, обновляем адрес")
            else:
                print(f"[!] Зарегистрирован: {full_id}")
            devices[full_id] = addr
            short = full_id.replace("ID:", "")
            short_to_full[short] = full_id
            last_seen[full_id] = time.time()

        # 2. Статус (начинается с "T")
        elif msg.startswith("T"):
            # Извлекаем короткий идентификатор (например "T2:DL:N2")
            try:
                short_key = msg.split(":AC")[0]  # до ":AC"
            except:
                return
            full_id = short_to_full.get(short_key)
            if full_id:
                last_seen[full_id] = time.time()
                device_states[full_id] = msg
                # Можно также обновить состояние в реальном времени, если нужно
            else:
                print(f"[?] Статус от неизвестного устройства: {short_key}")

        # 3. Любое другое сообщение (например, ответ на команду) – игнорируем,
        #    но можно обновить last_seen, если знаем от кого
        else:
            # Пытаемся найти устройство по адресу (медленно, но редко)
            for fid, faddr in devices.items():
                if faddr == addr:
                    last_seen[fid] = time.time()
                    break

    def error_received(self, exc):
        print(f"[!] UDP ошибка: {exc}")

# ---------- Эндпоинты ----------
class Command(BaseModel):
    device_id: str
    color: str
    status: int

@app.get("/devices")
async def get_devices():
    return {"online": list(devices.keys()), "states": device_states}

@app.post("/control/lamp")
async def control_lamp(cmd: Command):
    if disco_active:
        raise HTTPException(409, "Disco mode active")
    if cmd.device_id not in devices:
        raise HTTPException(404, "Device offline")
    success = await send_command(cmd.device_id, f"{cmd.color}{cmd.status}")
    if not success:
        raise HTTPException(500, "Send failed")
    return {"status": "sent"}

@app.get("/broadcast/on")
async def broadcast_on():
    if not devices:
        raise HTTPException(400, "No devices")
    for did in list(devices.keys()):
        await send_command(did, "1111")
    return {"message": "Broadcast ON sent", "count": len(devices)}

@app.get("/broadcast/off")
async def broadcast_off():
    if not devices:
        raise HTTPException(400, "No devices")
    for did in list(devices.keys()):
        await send_command(did, "0000")
    return {"message": "Broadcast OFF sent", "count": len(devices)}

@app.get("/disco/start")
async def disco_start():
    global disco_active, disco_task, original_states
    if disco_active:
        raise HTTPException(400, "Already active")
    if not devices:
        raise HTTPException(400, "No devices")

    for did in devices:
        state_str = device_states.get(did)
        if state_str:
            parsed = parse_state(state_str)
            original_states[did] = parsed or {'R':0,'Y':0,'G':0,'B':0}
        else:
            original_states[did] = {'R':0,'Y':0,'G':0,'B':0}

    disco_active = True
    disco_task = asyncio.create_task(disco_loop())
    return {"message": "Disco started", "devices": len(original_states)}

@app.get("/disco/stop")
async def disco_stop():
    global disco_active, disco_task, original_states
    if not disco_active:
        raise HTTPException(400, "Not active")

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
        if did in devices:
            for color, status in states.items():
                await send_command(did, f"{color}{status}")
            restored += 1
    original_states.clear()
    return {"message": "Disco stopped", "restored": restored}

async def disco_loop(interval: float = 0.5):
    while disco_active:
        for did in list(devices.keys()):
            for color in ['R','Y','G','B']:
                await send_command(did, f"{color}{random.randint(0,1)}")
        await asyncio.sleep(interval)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
