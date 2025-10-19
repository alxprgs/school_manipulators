import json
import time
import asyncio
import datetime
from server.core.paths import DEVICES_JSON
from fastapi import WebSocket
from typing import Literal


class WebSocketManager:
    def __init__(self):
        self.connections: dict[str, WebSocket] = {}
        self.last_seen: dict[str, float] = {}
        self.devices: dict = {}
        self.timeout = 30
        self._log("WebSocketManager initialized")

        self.load_devices()

    def _log(self, msg: str, level: str = "INFO"):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        print(f"[{ts}] [{level}] {msg}")

    async def _cleanup_task(self):
        while True:
            now = time.time()
            for key in list(self.last_seen):
                if now - self.last_seen[key] > self.timeout:
                    self._log(f"{key} timed out (no ping for {self.timeout}s)", "WARN")
                    try:
                        table, rest = key.split(".", 1)
                        if "_" not in rest:
                            device, id_str = rest, "0"
                        else:
                            device, id_str = rest.rsplit("_", 1)
                        await self.disconnect(table, device, int(id_str))
                    except Exception as e:
                        self._log(f"Cleanup error for {key}: {e}", "ERROR")
            await asyncio.sleep(5)

    def load_devices(self):
        try:
            with open(DEVICES_JSON, "r", encoding="utf-8") as f:
                self.devices = json.load(f)
            self._log(f"Devices loaded ({len(self.devices)} tables)")
        except Exception as e:
            self._log(f"Failed to load devices.json: {e}", "ERROR")
            self.devices = {}

    async def connect(self, table: Literal["table1", "table2", "table3", "table4"], device: str, id: int, websocket: WebSocket):
        key = f"{table}.{device}_{id}"
        await websocket.accept()
        self.connections[key] = websocket
        self.last_seen[key] = time.time()
        self._log(f"[+] {key} connected")

    async def disconnect(self, table: Literal["table1", "table2", "table3", "table4"], device: str, id: int):
        key = f"{table}.{device}_{id}"
        self.connections.pop(key, None)
        self.last_seen.pop(key, None)
        self._log(f"[-] {key} disconnected")

    async def send_to(self, key: str, data: dict) -> bool:
        ws = self.connections.get(key)
        if not ws:
            self._log(f"{key} offline", "WARN")
            return False
        try:
            await ws.send_text(json.dumps(data))
            self.last_seen[key] = time.time()
            return True
        except Exception as e:
            self._log(f"Send error to {key}: {e}", "ERROR")
            return False

    async def set_light_stand_color(self, table: Literal["table1", "table2", "table3", "table4"], id: int, color: Literal["red", "orange", "green", "blue"], status: bool):
        key = f"{table}.light_stand_{id}"
        if not self.is_online(key):
            self._log(f"{key} offline", "WARN")
            return False
        data = {
            "action": "set_light_color",
            "payload": {"color": color, "enabled": status}
        }
        return await self.send_to(key, data)

    async def set_remote_controller_color(self, table: Literal["table1", "table2", "table3", "table4"], color: Literal["red", "orange", "green", "blue"], status: bool):
        key = f"{table}.remote_controller_0"
        if not self.is_online(key):
            self._log(f"{key} offline", "WARN")
            return False
        data = {
            "action": "set_light_color",
            "payload": {"color": color, "enabled": status}
        }
        return await self.send_to(key, data)

    async def set_table_colors(self, table: Literal["table1", "table2", "table3", "table4"], main_color: Literal["red", "orange", "green", "blue"], active: bool = True, light_count: int = 2):
        colors = ["red", "orange", "green", "blue"]

        for color in colors:
            status = color == main_color if active else False
            await self.set_remote_controller_color(table, color, status)

            for i in range(1, light_count + 1):
                await self.set_light_stand_color(table, i, color, status)

        self._log(f"[~] Updated colors on {table}: {main_color} -> {'ON' if active else 'RESET'}")

    async def broadcast_table(self, table: Literal["table1", "table2", "table3", "table4"], data: dict):
        msg = json.dumps(data)
        for key, ws in list(self.connections.items()):
            if key.startswith(f"{table}."):
                try:
                    await ws.send_text(msg)
                    self.last_seen[key] = time.time()
                except Exception as e:
                    self._log(f"Broadcast error to {key}: {e}", "ERROR")
                    parts = key.split(".")
                    if len(parts) == 2 and "_" in parts[1]:
                        device, id_str = parts[1].rsplit("_", 1)
                        await self.disconnect(parts[0], device, int(id_str))

    async def broadcast_table_filtered(self, table: Literal["table1", "table2", "table3", "table4"], device_prefix: str, data: dict):
        msg = json.dumps(data)
        for key, ws in list(self.connections.items()):
            if key.startswith(f"{table}.{device_prefix}"):
                try:
                    await ws.send_text(msg)
                    self.last_seen[key] = time.time()
                except Exception as e:
                    self._log(f"Filtered broadcast error to {key}: {e}", "ERROR")

    async def broadcast_all(self, data: dict):
        msg = json.dumps(data)
        for key, ws in list(self.connections.items()):
            try:
                await ws.send_text(msg)
                self.last_seen[key] = time.time()
            except Exception as e:
                self._log(f"Broadcast error to {key}: {e}", "ERROR")
                parts = key.split(".")
                if len(parts) == 2 and "_" in parts[1]:
                    device, id_str = parts[1].rsplit("_", 1)
                    await self.disconnect(parts[0], device, int(id_str))

    def list_table(self, table: str) -> list[str]:
        return [key for key in self.connections if key.startswith(f"{table}.")]

    def is_online(self, key: str) -> bool:
        return key in self.connections

    def get_online_map(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for key in self.connections:
            table, rest = key.split(".", 1)
            result.setdefault(table, []).append(rest)
        return result

    def get_device_info(self, key: str) -> dict:
        if key not in self.connections:
            return {"online": False}
        return {
            "key": key,
            "online": True,
            "last_seen_sec": round(time.time() - self.last_seen[key], 1)
        }

    def is_known_device(self, table: Literal["table1", "table2", "table3", "table4"], device: str) -> bool:
        return table in self.devices and device in self.devices[table]
    

    async def shutdown(self):
        for key, ws in list(self.connections.items()):
            try:
                await ws.close()
            except Exception:
                pass
        self.connections.clear()
        self.last_seen.clear()

