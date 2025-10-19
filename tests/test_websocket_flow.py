# tests/test_websocket_flow.py
import pytest
from starlette.websockets import WebSocketDisconnect


def _auth(ws, code: str):
    ws.send_json({"action": "auth", "auth_code": code})
    msg = ws.receive_json()
    assert msg.get("status") is True
    assert "authorized" in msg.get("msg", "").lower()


def test_auth_success_button(client, expected_code):
    with client.websocket_connect("/ws/table1/button/1") as ws:
        code = expected_code("table1", "button_1")
        _auth(ws, code)


def test_auth_failure_wrong_code(client):
    with client.websocket_connect("/ws/table1/button/1") as ws:
        ws.send_json({"action": "auth", "auth_code": "deadbeefdead"})
        data = ws.receive_json()
        assert data.get("status") is False
        assert "wrong device code" in data.get("msg", "").lower()
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_json_ping_pong_after_auth(client, expected_code):
    with client.websocket_connect("/ws/table1/remote_controller/0") as ws:
        code = expected_code("table1", "remote_controller_0")
        _auth(ws, code)

        ws.send_json({"action": "ping"})
        pong = ws.receive_json()
        assert pong.get("msg") == "Pong"


def test_joystick_routes_to_lightstand(client, expected_code):
    with client.websocket_connect("/ws/table1/light_stand/1") as ws_ls:
        code_ls = expected_code("table1", "light_stand_1")
        _auth(ws_ls, code_ls)

        with client.websocket_connect("/ws/table1/remote_controller/0") as ws_rc:
            code_rc = expected_code("table1", "remote_controller_0")
            _auth(ws_rc, code_rc)

            ws_rc.send_json({
                "action": "joystick",
                "payload": {"manipulator_id": 1, "x": 25, "y": -10}
            })

            msg_to_ls = ws_ls.receive_json()
            assert msg_to_ls["action"] == "action_manipulator_xy"
            assert msg_to_ls["payload"] == {"x": 25, "y": -10}


def test_button_requires_emergency_then_toggles_party(client, expected_code):
    """
    Сценарий:
      1) Кнопка жмётся без аварии -> ошибка
      2) Пульт включает emergency -> зелёный -> красный на устройства (мы не проверяем цвета, только поток)
      3) Кнопка включает party mode -> подтверждение
      4) Кнопка повторно -> party mode stopped
    """

    with client.websocket_connect("/ws/table1/button/1") as ws_btn:
        code_btn = expected_code("table1", "button_1")
        _auth(ws_btn, code_btn)

        ws_btn.send_json({"action": "button_press"})
        resp = ws_btn.receive_json()
        assert resp.get("status") is False
        assert "not enabled" in resp.get("msg", "").lower()

        with client.websocket_connect("/ws/table1/remote_controller/0") as ws_rc:
            code_rc = expected_code("table1", "remote_controller_0")
            _auth(ws_rc, code_rc)

            ws_rc.send_json({"action": "emergency_button", "payload": {"type": "emergency"}})
            ack = ws_rc.receive_json()
            assert ack.get("status") is True
            assert "emergency stop" in ack.get("msg", "").lower()

            ws_btn.send_json({"action": "button_press"})
            started = ws_btn.receive_json()
            assert started.get("status") is True
            assert "party mode started" in started.get("msg", "").lower()

            ws_btn.send_json({"action": "button_press"})
            stopped = ws_btn.receive_json()
            assert stopped.get("status") is True
            assert "party mode stopped" in stopped.get("msg", "").lower()

            ws_rc.send_json({"action": "emergency_button", "payload": {"type": "release"}})

            ack2 = None
            for _ in range(20):
                msg = ws_rc.receive_json()
                if isinstance(msg, dict) and "status" in msg:
                    ack2 = msg
                    break
            assert ack2 is not None, "Не пришёл ACK на release"
            assert ack2.get("status") is True
            assert "released" in (ack2.get("msg") or "").lower()

def test_button_unsupported_action(client, expected_code):
    with client.websocket_connect("/ws/table1/button/1") as ws:
        code = expected_code("table1", "button_1")
        _auth(ws, code)

        ws.send_json({"action": "something_else"})
        resp = ws.receive_json()
        assert resp.get("status") is False
        assert "unsupported" in resp.get("msg", "").lower()
