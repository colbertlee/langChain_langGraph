"""
Headless Agent CLI Demo。

用法::

    python demo_headless.py "你好，介绍一下你自己"
    python demo_headless.py                       # 默认 query：'用一句话介绍 Headless Agent'

特性
----
- 零 Web 依赖：仅 stdlib + ai_agent 本地模块；
- 实时打印事件流：TOKEN 增量直出到 stdout，其它事件以 ``[TYPE]`` 前缀显示；
- 最终汇总：DONE 事件打出最终文本与耗时。

注意
----
- 真正的 LLM 调用需要配置 OPENAI_API_KEY（或其它 provider）；
  未配置时 AILgent 内部会走降级路径，返回错误文本，Demo 也会照常打印 ERROR 事件。
"""
from __future__ import annotations

import asyncio
import sys
import time

from headless_agent import HeadlessAgent
from headless_events import HeadlessEventType


DEFAULT_QUERY = "用一句话介绍 Headless Agent"


async def _run(query: str) -> int:
    t0 = time.monotonic()
    print(f"[demo] query: {query!r}\n")

    agent = HeadlessAgent()
    saw_done = False
    saw_error = False

    try:
        async for ev in agent.stream(query):
            if ev.type == HeadlessEventType.TOKEN:
                # 文本增量：直出，无前缀
                sys.stdout.write(ev.data.get("delta", ""))
                sys.stdout.flush()
            elif ev.type == HeadlessEventType.TOOL_CALL:
                print(f"\n[TOOL_CALL] {ev.data.get('name')}({ev.data.get('args')})", flush=True)
            elif ev.type == HeadlessEventType.TOOL_RESULT:
                print(f"[TOOL_RESULT] {ev.data.get('name')} -> {ev.data.get('result')}", flush=True)
            elif ev.type == HeadlessEventType.PERMISSION_REQUEST:
                print(f"[PERMISSION_REQUEST] {ev.data.get('tool')}", flush=True)
            elif ev.type == HeadlessEventType.PERMISSION_RESPONSE:
                tag = "approved" if ev.data.get("approved") else "denied"
                print(
                    f"[PERMISSION_RESPONSE] {ev.data.get('tool')} -> {tag} "
                    f"({ev.data.get('reason')})",
                    flush=True,
                )
            elif ev.type == HeadlessEventType.ERROR:
                saw_error = True
                print(f"\n[ERROR] {ev.data.get('message')}", flush=True)
            elif ev.type == HeadlessEventType.DONE:
                saw_done = True
                print(
                    f"\n[DONE] final_len={len(ev.data.get('final_text') or '')} "
                    f"elapsed={time.monotonic() - t0:.2f}s",
                    flush=True,
                )
    except KeyboardInterrupt:
        print("\n[demo] interrupted by user", flush=True)
        return 130

    if not saw_done:
        print("\n[demo] WARNING: stream ended without DONE event", flush=True)
        return 1
    return 0 if not saw_error else 2


def main() -> int:
    query = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_QUERY
    try:
        return asyncio.run(_run(query))
    except Exception as e:  # pragma: no cover - 防御性
        print(f"[demo] fatal: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())