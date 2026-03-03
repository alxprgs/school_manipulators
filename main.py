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

# Общий словарь всех устройств (для отправки команд и last_seen)
devices: Dict[str, Tuple[str, int]] = {}          # полный ID -> (ip, port)

# Словари по типам
lamps: Dict[str, Tuple[str, int]] = {}            # только лампы
remotes: Dict[str, Tuple[str, int]] = {}          # только пульты

# Состояния
lamp_states: Dict[str, str] = {}                  # полный статус лампы (строка)
remote_states: Dict[str, dict] = {}                # распарсенные данные пульта

# Короткие идентификаторы
short_to_full: Dict[str, str] = {}                 # короткий ID -> полный ID
last_seen: Dict[str, float] = {}                    # для всех устройств

disco_active = False
disco_task: Optional[asyncio.Task] = None
original_states: Dict[str, Dict[str, int]] = {}     # сохранённые состояния ламп перед дискотекой


# ---------- Вспомогательные функции ----------
def parse_lamp_state(state_str: str) -> Dict[str, int]:
    """Из строки 'T1:DL:N1:AC:R0:Y0:G0:B0' достаёт {'R':0, 'Y':0, 'G':0, 'B':0}"""
    parts = state_str.split(':')
    state = {}
    for part in parts:
        if part and part[0] in ('R', 'Y', 'G', 'B') and len(part) >= 2:
            color = part[0]
            value = int(part[1])
            state[color] = value
    return state


def parse_remote_state(state_str: str) -> dict:
    """Парсит строку состояния пульта в словарь."""
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
    """Отправляет UDP-команду устройству."""
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
    # Удаляем из short_to_full
    short = device_id.replace("ID:", "")
    short_to_full.pop(short, None)

    # Удаляем из общих словарей
    devices.pop(device_id, None)
    last_seen.pop(device_id, None)

    # Удаляем из словарей по типам
    lamps.pop(device_id, None)
    remotes.pop(device_id, None)
    lamp_states.pop(device_id, None)
    remote_states.pop(device_id, None)
    original_states.pop(device_id, None)  # для дискотеки

    print(f"[!] Устройство {device_id} удалено")


async def restore_device(device_id: str):
    """Восстанавливает состояние лампы после дискотеки (используется в disco/stop)."""
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
            # Определяем тип
            if ":DL:" in full_id:
                device_type = "lamp"
                lamps[full_id] = addr
            elif ":PT:" in full_id:
                device_type = "remote"
                remotes[full_id] = addr
            else:
                print(f"[!] Неизвестный тип устройства: {full_id}")
                return

            # Добавляем в общий словарь
            devices[full_id] = addr
            short = full_id.replace("ID:", "")
            short_to_full[short] = full_id
            last_seen[full_id] = time.time()
            print(f"[!] Зарегистрирован {device_type}: {full_id}")

        # 2. Статус (начинается с "T")
        elif msg.startswith("T"):
            try:
                # Извлекаем первые три части: T<табл>:<тип>:N<номер>
                parts = msg.split(':')
                if len(parts) < 3:
                    return
                short_key = f"{parts[0]}:{parts[1]}:{parts[2]}"
            except:
                return

            full_id = short_to_full.get(short_key)
            if not full_id:
                print(f"[?] Статус от неизвестного устройства: {short_key}")
                return

            last_seen[full_id] = time.time()

            if full_id in lamps:
                # Для лампы сохраняем строку целиком (нужно для дискотеки)
                lamp_states[full_id] = msg
            elif full_id in remotes:
                # Для пульта парсим детально
                state = parse_remote_state(msg)
                remote_states[full_id] = state
            else:
                print(f"[?] Устройство {full_id} не найдено ни в lamps, ни в remotes")

        # 3. Любое другое сообщение – пытаемся обновить last_seen по адресу
        else:
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
    """Общий список всех устройств (для отладки)."""
    return {"online": list(devices.keys())}


@app.get("/lamps")
async def get_lamps():
    """Список ламп и их состояний."""
    return {"online": list(lamps.keys()), "states": lamp_states}


@app.get("/remotes")
async def get_remotes():
    """Список пультов и их последних состояний."""
    return {"online": list(remotes.keys()), "states": remote_states}


@app.get("/remote/{device_id}")
async def get_remote_state(device_id: str):
    """Получить состояние конкретного пульта."""
    if device_id not in remotes:
        raise HTTPException(404, "Remote not found")
    return remote_states.get(device_id, {})


@app.post("/control/lamp")
async def control_lamp(cmd: Command):
    """Управление лампой (одиночный светодиод)."""
    if cmd.device_id not in lamps:
        raise HTTPException(404, "Lamp not found or not a lamp")
    if disco_active:
        raise HTTPException(409, "Disco mode is active, control disabled")
    success = await send_command(cmd.device_id, f"{cmd.color}{cmd.status}")
    if not success:
        raise HTTPException(500, "Send failed")
    return {"status": "sent"}


@app.post("/control/remote")
async def control_remote(cmd: Command):
    """Управление светодиодом на пульте."""
    if cmd.device_id not in remotes:
        raise HTTPException(404, "Remote not found or not a remote")
    # Дискотека не влияет на пульты, поэтому проверку disco_active не делаем
    success = await send_command(cmd.device_id, f"{cmd.color}{cmd.status}")
    if not success:
        raise HTTPException(500, "Send failed")
    return {"status": "sent"}


@app.get("/broadcast/on")
async def broadcast_on():
    """Включить все светодиоды на всех лампах."""
    if not lamps:
        raise HTTPException(400, "No lamps connected")
    for did in list(lamps.keys()):
        await send_command(did, "1111")
    return {"message": "Broadcast ON sent", "count": len(lamps)}


@app.get("/broadcast/off")
async def broadcast_off():
    """Выключить все светодиоды на всех лампах."""
    if not lamps:
        raise HTTPException(400, "No lamps connected")
    for did in list(lamps.keys()):
        await send_command(did, "0000")
    return {"message": "Broadcast OFF sent", "count": len(lamps)}


@app.get("/disco/start")
async def disco_start():
    """Запустить дискотеку (только для ламп)."""
    global disco_active, disco_task, original_states
    if disco_active:
        raise HTTPException(400, "Disco already active")
    if not lamps:
        raise HTTPException(400, "No lamps connected")

    # Сохраняем текущие состояния ламп
    for did in lamps:
        state_str = lamp_states.get(did)
        if state_str:
            parsed = parse_lamp_state(state_str)
            original_states[did] = parsed or {'R': 0, 'Y': 0, 'G': 0, 'B': 0}
        else:
            original_states[did] = {'R': 0, 'Y': 0, 'G': 0, 'B': 0}

    disco_active = True
    disco_task = asyncio.create_task(disco_loop())
    return {"message": "Disco started", "devices": len(original_states)}


@app.get("/disco/stop")
async def disco_stop():
    """Остановить дискотеку и восстановить исходные состояния ламп."""
    global disco_active, disco_task, original_states
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
        if did in lamps:  # проверяем, что лампа ещё онлайн
            for color, status in states.items():
                await send_command(did, f"{color}{status}")
            restored += 1
    original_states.clear()
    return {"message": "Disco stopped", "restored": restored}


async def disco_loop(interval: float = 0.3):
    """Цикл дискотеки – работает только с лампами."""
    # Прелюдия: поочередное включение цветов
    print("[*] Прелюдия: включение цветов по порядку")
    colors_on = ['R', 'Y', 'G', 'B']
    for color in colors_on:
        if not disco_active:
            return
        for did in list(lamps.keys()):
            await send_command(did, f"{color}1")
        await asyncio.sleep(interval)

    await asyncio.sleep(interval)

    # Выключение в обратном порядке
    print("[*] Прелюдия: выключение цветов в обратном порядке")
    colors_off = ['B', 'G', 'Y', 'R']
    for color in colors_off:
        if not disco_active:
            return
        for did in list(lamps.keys()):
            await send_command(did, f"{color}0")
        await asyncio.sleep(interval)

    await asyncio.sleep(interval)

    # Основная дискотека
    print("[*] Начинаем беспорядочную дискотеку!")
    while disco_active:
        for did in list(lamps.keys()):
            color = random.choice(['R', 'Y', 'G', 'B'])
            status = random.randint(0, 1)
            await send_command(did, f"{color}{status}")
        await asyncio.sleep(interval)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
