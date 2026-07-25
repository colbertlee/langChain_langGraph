"""SSE 流式聊天协议验证 — 验证格式与前端 fetchEventStream 解析一致。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from app import app


def test_sse_chat_protocol():
    client = TestClient(app)
    with client.stream("POST", "/api/chat/stream", json={"message": "hi"}) as resp:
        assert resp.status_code == 200, f"status={resp.status_code}"
        ct = resp.headers.get("content-type", "")
        assert ct.startswith("text/event-stream"), f"ct={ct}"

        # 收集全部 SSE 事件
        events = []
        buffer = ""
        for raw in resp.iter_bytes():
            if not raw:
                continue
            buffer += raw.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                ev = {}
                for line in block.splitlines():
                    if line.startswith("event:"):
                        ev["event"] = line[len("event:"):].strip()
                    elif line.startswith("data:"):
                        ev.setdefault("data", "")
                        ev["data"] += line[len("data:"):].strip()
                if ev:
                    events.append(ev)

        print(f"SSE events received: {len(events)}")
        for e in events:
            data_preview = e.get("data", "")[:80]
            print(f"  - event={e.get('event', 'message')!r} data={data_preview!r}")

        assert len(events) >= 2, "expected at least start + end events"
        # 最后一个必须是 end
        assert events[-1].get("event") == "end", f"last event: {events[-1]}"
        print("[PASS] SSE chat protocol roundtrip")


if __name__ == "__main__":
    test_sse_chat_protocol()