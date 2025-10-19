from __future__ import annotations

import hashlib
import hmac
import json
import time
import asyncio
import aiofiles
from server.core.config import settings
from server.core.paths import DEVICES_JSON

from server.core.LoggingModule import logger

devices_data: dict = {}
_last_reload: float = 0.0
_reload_lock = asyncio.Lock()

async def load_devices() -> dict:
    try:
        async with aiofiles.open(DEVICES_JSON, "r", encoding="utf-8") as f:
            content = await f.read()
            return json.loads(content)
    except FileNotFoundError:
        logger.error("Файл устройств не найден: %s", DEVICES_JSON)
        return {}
    except json.JSONDecodeError as e:
        logger.exception("Ошибка парсинга JSON %s: %s", DEVICES_JSON, e)
        return {}
    except Exception as e:
        logger.exception("Ошибка загрузки устройств: %s", e)
        return {}


def _normalize_mac(mac: str) -> str:
    return mac.lower().replace(":", "").replace("-", "").strip()


def _normalize_ip(ip: str) -> str:
    return ip.strip()


def _expected_code(mac: str, ip: str, length: int = 12) -> str:
    secret = getattr(settings, "DEVICE_SECRET", None) or "123456789"
    if not getattr(settings, "DEVICE_SECRET", None):
        logger.warning("DEVICE_SECRET не задан — используется небезопасный fallback!")
    data = f"{_normalize_mac(mac)}-{_normalize_ip(ip)}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), data, hashlib.sha256).hexdigest()
    return digest[:length]

async def check_code(
    table: str, 
    device_name: str,
    device_code: str,
    autoreload: bool = False
) -> bool:
    global devices_data, _last_reload

    if autoreload and (time.time() - _last_reload > 10):
        async with _reload_lock:
            if time.time() - _last_reload > 10:
                logger.debug("Перезагрузка данных устройств...")
                devices_data = await load_devices()
                _last_reload = time.time()

    try:
        dev = devices_data[table][device_name]
        device_ip = dev["ip"]
        device_mac = dev["mac"]
    except KeyError:
        logger.warning("Запрошено несуществующее устройство: table=%s name=%s", table, device_name)
        return False
    except Exception:
        logger.exception("Неожиданная ошибка при получении данных устройства")
        return False

    try:
        expected = _expected_code(device_mac, device_ip)
        if hmac.compare_digest(expected, device_code):
            return True
        logger.info("Неверный код для %s/%s", table, device_name)
        return False
    except Exception:
        logger.exception("Ошибка проверки кода доступа для %s/%s", table, device_name)
        return False

async def init_devices_cache() -> None:
    global devices_data, _last_reload
    devices_data = await load_devices()
    _last_reload = time.time()
    logger.info("Данные устройств загружены (%d таблиц)", len(devices_data))
