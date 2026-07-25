"""测试 WebSocket 流式聊天（前端 initWS 使用）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app import app


def test_websocket_chat():
    client = TestClient(app)
    with client.websocket_connect("/api/chat/stream") as ws:
        # 发送消息
        ws.send_json({"message": "ping", "session_id": "ws-test-sid"})
        messages = []
        # 接收直到 complete 或 timeout
        for _ in range(100):
            try:
                data = ws.receive_json()
            except Exception:
                break
            messages.append(data)
            if data.get("type") in ("complete", "error"):
                break
        print(f"WS messages count: {len(messages)}")
        for m in messages:
            print(f"  - type={m.get('type')!r} data={str(m)[:120]}")
        assert len(messages) > 0, "expected at least one WS message"
        # 必须有 complete 或 error
        assert any(m.get("type") in ("complete", "error") for m in messages)
        print("[PASS] WebSocket chat stream roundtrip")


if __name__ == "__main__":
    test_websocket_chat()