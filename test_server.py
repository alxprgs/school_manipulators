import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from main import app, devices, device_states, handle_tcp_client

# Настройки для тестов
TCP_HOST = "127.0.0.1"
TCP_PORT = 8888

class MockArduinoClient:
    def __init__(self, device_id, host="127.0.0.1", port=8888):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.connected = False
        self.reconnect_count = 0
        self.stop_event = asyncio.Event()

    async def run(self):
        """Цикл, имитирующий void loop() с логикой переподключения"""
        while not self.stop_event.is_set():
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                self.connected = True
                # При подключении сразу шлем ID (как в setup/connectToServer)
                writer.write(f"ID:{self.device_id}\n".encode())
                await writer.drain()
                
                # Ждем данных или разрыва соединения
                while not self.stop_event.is_set():
                    data = await reader.read(1024)
                    if not data:
                        break # Соединение закрыто сервером
                
                writer.close()
                await writer.wait_closed()
            except (ConnectionRefusedError, OSError):
                self.connected = False
                self.reconnect_count += 1
                await asyncio.sleep(0.5) # Пауза перед попыткой (в тестах быстрее, чем в жизни)
            finally:
                self.connected = False

@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def run_tcp_server():
    server = await asyncio.start_server(handle_tcp_client, TCP_HOST, TCP_PORT)
    task = asyncio.create_task(server.serve_forever())
    yield
    task.cancel()
    await server.wait_closed()
    devices.clear() # Очищаем устройства между тестами

@pytest_asyncio.fixture(loop_scope="function")
async def client():
    # В новых версиях httpx используем transport
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

@pytest_asyncio.fixture(loop_scope="function")
async def mock_arduino():
    """Фикстура, имитирующая подключение Arduino по TCP"""
    reader, writer = await asyncio.open_connection(TCP_HOST, TCP_PORT)
    yield reader, writer
    writer.close()
    await writer.wait_closed()


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_device_registration(mock_arduino, client):
    """Проверка регистрации устройства через TCP ID"""
    reader, writer = mock_arduino
    
    # Имитируем отправку ID от Arduino
    device_id = "T1:DB:N1"
    writer.write(f"ID:{device_id}\n".encode())
    await writer.drain()
    
    # Даем серверу немного времени на обработку
    await asyncio.sleep(0.1)
    
    # Проверяем через API, появилось ли устройство в сети
    response = await client.get("/devices")
    assert response.status_code == 200
    assert device_id in response.json()["online"]


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_button_status_update(mock_arduino, client):
    """Проверка обновления состояния кнопки при получении данных по TCP"""
    reader, writer = mock_arduino
    device_id = "T1:DB:N1"
    
    # Сначала регистрируем
    writer.write(f"ID:{device_id}\n".encode())
    # Отправляем статус кнопки (нажата)
    writer.write(f"{device_id}:BS1\n".encode())
    await writer.drain()
    
    await asyncio.sleep(0.1)
    
    # Проверяем, сохранилось ли состояние на сервере
    response = await client.get("/devices")
    assert response.json()["states"][device_id] == f"{device_id}:BS1"


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_control_lamp_command(mock_arduino, client):
    """Проверка отправки команды на лампу через API -> TCP"""
    reader, writer = mock_arduino
    device_id = "T1:DL:N1"
    
    # Регистрируем лампу
    writer.write(f"ID:{device_id}\n".encode())
    await writer.drain()
    await asyncio.sleep(0.1)
    
    # Отправляем команду через HTTP API
    payload = {
        "device_id": device_id,
        "color": "R",
        "status": 1
    }
    response = await client.post("/control/lamp", json=payload)
    assert response.status_code == 200
    
    # Проверяем, пришло ли сообщение в TCP-канал (Arduino должна его получить)
    data = await reader.read(1024)
    received_msg = data.decode().strip()
    assert received_msg == "CS:S:CR:S1"

@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_control_non_existent_device(client):
    """Проверка ошибки 404 при попытке управлять несуществующим устройством"""
    payload = {
        "device_id": "T99:DL:N99",
        "color": "G",
        "status": 1
    }
    response = await client.post("/control/lamp", json=payload)
    assert response.status_code == 404
    assert response.json()["detail"] == "Устройство не в сети"


@pytest.mark.asyncio
@pytest.mark.timeout(10)
async def test_server_restart_reconnection():
    """Тест переподключения с явным завершением задач"""
    device_id = "T2:DL:N1"
    host, port = "127.0.0.1", 8889
    
    # 1. Запуск 1
    server = await asyncio.start_server(handle_tcp_client, host, port)
    arduino = MockArduinoClient(device_id, host, port)
    arduino_task = asyncio.create_task(arduino.run())
    
    await asyncio.sleep(0.5)
    assert device_id in devices
    
    # 2. Остановка сервера
    server.close()
    await server.wait_closed()
    devices.clear()
    await asyncio.sleep(0.5) # Ждем, пока клиент поймет, что связи нет
    
    # 3. Рестарт сервера
    new_server = await asyncio.start_server(handle_tcp_client, host, port)
    await asyncio.sleep(1.0) # Ждем переподключения
    
    try:
        assert device_id in devices
    finally:
        # Останавливаем клиента
        arduino_task.cancel()
        try:
            await arduino_task
        except asyncio.CancelledError:
            pass

        # Закрываем сервер
        new_server.close()
        await new_server.wait_closed()