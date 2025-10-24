import pytest

def _auth(ws, code: str):
    ws.send_json({"action": "auth", "auth_code": code})
    msg = ws.receive_json()
    assert msg.get("status") is True
    assert "authorized" in (msg.get("msg") or "").lower()

@pytest.mark.parametrize(
    "path, table, device_key",
    [
        ("/ws/table1/remote_controller/0", "table1", "remote_controller_0"),
        ("/ws/table1/button/1",            "table1", "button_1"),
        ("/ws/table1/button/2",            "table1", "button_2"),
        ("/ws/table1/light_stand/1",       "table1", "light_stand_1"),
        ("/ws/table1/light_stand/2",       "table1", "light_stand_2"),
    ],
)
def test_auth_success_all_devices(client, expected_code, path, table, device_key):
    with client.websocket_connect(path) as ws:
        code = expected_code(table, device_key)
        _auth(ws, code)


@pytest.mark.parametrize(
    "path, table, device_key",
    [
        ("/ws/table1/remote_controller/0", "table1", "remote_controller_0"),
        ("/ws/table1/button/1",            "table1", "button_1"),
        ("/ws/table1/light_stand/1",       "table1", "light_stand_1"),
        ("/ws/table1/light_stand/2",       "table1", "light_stand_2"),
    ],
)
def test_ping_pong_all_devices(client, expected_code, path, table, device_key):
    with client.websocket_connect(path) as ws:
        code = expected_code(table, device_key)
        _auth(ws, code)

        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong.get("status") is True
        assert pong.get("msg") == "Pong"


@pytest.mark.parametrize(
    "manipulator_id, ls_path, ls_key",
    [
        (1, "/ws/table1/light_stand/1", "light_stand_1"),
        (2, "/ws/table1/light_stand/2", "light_stand_2"),
    ],
)
def test_joystick_routes_to_correct_lightstand(client, expected_code, manipulator_id, ls_path, ls_key):
    with client.websocket_connect(ls_path) as ws_ls:
        code_ls = expected_code("table1", ls_key)
        _auth(ws_ls, code_ls)

        with client.websocket_connect("/ws/table1/remote_controller/0") as ws_rc:
            code_rc = expected_code("table1", "remote_controller_0")
            _auth(ws_rc, code_rc)

            payload_xy = {"manipulator_id": manipulator_id, "x": 25, "y": -10}
            ws_rc.send_json({"action": "joystick", "payload": payload_xy})

            msg_to_ls = ws_ls.receive_json()
            assert msg_to_ls["action"] == "action_manipulator_xy"
            assert msg_to_ls["payload"] == {"x": 25, "y": -10}


def test_remote_controller_reauth_then_ping(client, expected_code):
    path = "/ws/table1/remote_controller/0"
    with client.websocket_connect(path) as ws:
        code = expected_code("table1", "remote_controller_0")
        _auth(ws, code)

        ws.send_json({"action": "ping"})
        msg = ws.receive_json()

        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong.get("status") is True
        assert pong.get("msg") == "Pong"
