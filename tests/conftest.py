# tests/conftest.py
import json
import os
import sys
import importlib
import pytest
from pathlib import Path
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

SERVER_DIR = PROJECT_ROOT / "server"
(SERVER_DIR / "templates").mkdir(parents=True, exist_ok=True)
(SERVER_DIR / "static").mkdir(parents=True, exist_ok=True)

DEVICES_JSON_CONTENT = {
    "table1": {
        "remote_controller_0": {"ip": "192.168.1.3",  "mac": "de:ad:be:ef:01:01"},
        "cam_0":               {"ip": "192.168.1.4",  "mac": "de:ad:be:ef:01:02"},
        "button_1":            {"ip": "192.168.1.5",  "mac": "de:ad:be:ef:01:03"},
        "button_2":            {"ip": "192.168.1.6",  "mac": "de:ad:be:ef:01:04"},
        "light_stand_1":       {"ip": "192.168.1.7",  "mac": "de:ad:be:ef:01:05"},
        "light_stand_2":       {"ip": "192.168.1.8",  "mac": "de:ad:be:ef:01:06"},
    },
    "table2": {
        "remote_controller_0": {"ip": "192.168.1.9",  "mac": "de:ad:be:ef:02:01"},
        "cam_0":               {"ip": "192.168.1.10", "mac": "de:ad:be:ef:02:02"},
        "button_1":            {"ip": "192.168.1.11", "mac": "de:ad:be:ef:02:03"},
        "button_2":            {"ip": "192.168.1.12", "mac": "de:ad:be:ef:02:04"},
        "light_stand_1":       {"ip": "192.168.1.13", "mac": "de:ad:be:ef:02:05"},
        "light_stand_2":       {"ip": "192.168.1.14", "mac": "de:ad:be:ef:02:06"},
    },
    "table3": {
        "remote_controller_0": {"ip": "192.168.1.15", "mac": "de:ad:be:ef:03:01"},
        "cam_0":               {"ip": "192.168.1.16", "mac": "de:ad:be:ef:03:02"},
        "button_1":            {"ip": "192.168.1.17", "mac": "de:ad:be:ef:03:03"},
        "button_2":            {"ip": "192.168.1.18", "mac": "de:ad:be:ef:03:04"},
        "light_stand_1":       {"ip": "192.168.1.19", "mac": "de:ad:be:ef:03:05"},
        "light_stand_2":       {"ip": "192.168.1.20", "mac": "de:ad:be:ef:03:06"},
    },
    "table4": {
        "remote_controller_0": {"ip": "192.168.1.21", "mac": "de:ad:be:ef:04:01"},
        "cam_0":               {"ip": "192.168.1.22", "mac": "de:ad:be:ef:04:02"},
        "button_1":            {"ip": "192.168.1.23", "mac": "de:ad:be:ef:04:03"},
        "button_2":            {"ip": "192.168.1.24", "mac": "de:ad:be:ef:04:04"},
        "light_stand_1":       {"ip": "192.168.1.25", "mac": "de:ad:be:ef:04:05"},
        "light_stand_2":       {"ip": "192.168.1.26", "mac": "de:ad:be:ef:04:06"},
    },
    "other": {
        "server": {"ip": "192.168.1.2", "mac": "de:ad:be:ef:00:01"},
        "switch": {"ip": "192.168.1.1"}
    }
}


def _fresh_import_server():
    for name in list(sys.modules):
        if name == "server" or name.startswith("server."):
            sys.modules.pop(name, None)
    server = importlib.import_module("server")
    importlib.import_module("server.routes.main_websocket")
    return server


@pytest.fixture(scope="function")
def app_and_env(tmp_path):
    data_root = tmp_path / "data_root"
    data_root.mkdir(parents=True, exist_ok=True)
    devices_path = data_root / "devices.json"
    devices_path.write_text(json.dumps(DEVICES_JSON_CONTENT, ensure_ascii=False, indent=2), encoding="utf-8")

    old_data_root = os.environ.get("DATA_ROOT")
    old_device_secret = os.environ.get("DEVICE_SECRET")
    os.environ["DATA_ROOT"] = str(data_root)
    os.environ["DEVICE_SECRET"] = "123456789"

    server = _fresh_import_server()
    app = server.app
    manager = server.manager

    yield app, manager

    if old_data_root is None:
        os.environ.pop("DATA_ROOT", None)
    else:
        os.environ["DATA_ROOT"] = old_data_root
    if old_device_secret is None:
        os.environ.pop("DEVICE_SECRET", None)
    else:
        os.environ["DEVICE_SECRET"] = old_device_secret


@pytest.fixture(scope="function")
def client(app_and_env):
    app, _ = app_and_env
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="function")
def expected_code():

    import importlib as _imp
    def _fn(table: str, device_key: str) -> str:
        mod = _imp.import_module("server.core.functions.auth")
        dev = mod.devices_data[table][device_key]
        return mod._expected_code(dev["mac"], dev["ip"])
    return _fn
