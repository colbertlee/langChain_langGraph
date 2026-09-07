"""真实 LLM Provider 冒烟测试（本地/CI 之外的手动验证脚本）

目的：
  1. 验证 AIAgent.run() 真能打通至少一家 LLM Provider（hello round-trip）
  2. 验证内置 file_ops 工具在安全层下能正常 list / read
  3. 验证 AIAgent.run_stream() 能产出结构化事件（SSE 兼容前端）

不可用于 CI：
  - 依赖真实 API key（计费 + 网络）
  - 输出非确定性（不同模型 / 温度可能产出不同回答）
  - 默认仅在环境变量至少一个 LLM_API_KEY_* 设置时跑

用法：
  export DEEPSEEK_API_KEY=sk-...
  python ai_agent/scripts/real_api_smoke.py
  python ai_agent/scripts/real_api_smoke.py --provider deepseek --model deepseek-chat
  python ai_agent/scripts/real_api_smoke.py --skip-agent   # 仅测工具，跳过 LLM 调用

产物：
  - stdout: 三段 PASS/FAIL 报告
  - evals/runs/<timestamp>_real_smoke/<round|tools|stream>.json（落盘凭据）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 避免 Windows 中文 ❌/✅ 在 GBK 控制台 print 炸 → 强制 UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# 复用 evals 落盘布局（与 ai_agent/evals/runs/ 对齐）
RUNS_DIR = ROOT / "evals" / "runs"


def _pick_provider() -> str:
    """从环境变量里挑第一个有 key 的 provider；无 key 时返回空串。"""
    candidates = [
        ("openai", "OPENAI_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("qwen", "QWEN_API_KEY"),
        ("minimax", "MINIMAX_API_KEY"),
        ("zhipu", "ZHIPU_API_KEY"),
        ("moonshot", "MOONSHOT_API_KEY"),
        ("doubao", "DOUBAO_API_KEY"),
        ("siliconflow", "SILICONFLOW_API_KEY"),
    ]
    for prov, env in candidates:
        v = os.getenv(env, "").strip()
        if v and not any(p in v.lower() for p in ("your", "sk-test", "sk-xxx", "placeholder")):
            return prov
    return ""


def _save_artifact(name: str, data: Dict[str, Any]) -> Path:
    """把 round / tools / stream 的结果落盘到 evals/runs/<ts>_real_smoke/."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    out_dir = RUNS_DIR / f"{ts}_real_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    fp = out_dir / f"{name}.json"
    fp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return fp


# ──────────────────────────── 阶段 A：LLM hello ────────────────────────────
def smoke_agent_hello(provider: str, model: str) -> Dict[str, Any]:
    """跑 agent.run('你好') 验 LLM 真打通。"""
    from agent import AIAgent

    print(f"\n[A] LLM hello  ·  provider={provider} model={model}")
    agent = AIAgent()
    t0 = time.time()
    try:
        reply = agent.run("你好，请用一句话自我介绍")
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        return {
            "ok": False,
            "elapsed_ms": elapsed,
            "provider": provider,
            "model": model,
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(limit=5),
        }
    elapsed = int((time.time() - t0) * 1000)

    ok = bool(reply) and "错误" not in reply[:10] and len(reply) >= 4
    print(f"    {'PASS' if ok else 'FAIL'}  ({elapsed}ms)  reply={reply[:80]!r}")
    return {
        "ok": ok,
        "elapsed_ms": elapsed,
        "provider": provider,
        "model": model,
        "reply": reply,
        "reply_len": len(reply) if reply else 0,
    }


# ──────────────────────────── 阶段 B：工具直调 ────────────────────────────
def smoke_tools_direct() -> Dict[str, Any]:
    """不经过 LLM，直接 invoke file_ops 工具，验证工具 + 安全层。

    注：用相对子目录 `tests` 而非 `ROOT` 或 `.` 是有意的：
    - 安全层 `validate_safe_path` 对纯 `.` / 绝对路径会拒（已知怪行为）
    - 对真实业务（list 仓库内的子目录）足够代表性
    """
    print("\n[B] 工具直调  ·  file_ops(subcommand=list, path=tests)")
    try:
        # 走 v2 slim 默认入口
        from v2_slim.tools_v2 import file_ops
        from security import set_security_instance
        from security import SecurityModule
        set_security_instance(SecurityModule())

        t0 = time.time()
        result = file_ops.invoke(
            {"subcommand": "list", "path": "tests", "recursive": False}
        )
        elapsed = int((time.time() - t0) * 1000)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc(limit=5)}

    ok = isinstance(result, str) and result and "❌" not in result[:30]
    preview = result[:200] if isinstance(result, str) else str(result)[:200]
    print(f"    {'PASS' if ok else 'FAIL'}  ({elapsed}ms)  preview={preview!r}")
    return {"ok": ok, "elapsed_ms": elapsed, "preview": preview, "len": len(result) if isinstance(result, str) else 0}


# ──────────────────────────── 阶段 C：流式事件 ────────────────────────────
def smoke_agent_stream(provider: str, model: str) -> Dict[str, Any]:
    """跑 agent.run_stream 产出 SSE 事件，验证前端能解析。"""
    from agent import AIAgent

    print(f"\n[C] 流式事件  ·  run_stream('1+1=?')")
    agent = AIAgent()
    t0 = time.time()
    chunks: list[str] = []
    events: list[dict] = []
    try:
        for evt in agent.run_stream("1+1 等于几？只用数字回答"):
            # run_stream 的事件可能是 dict（结构化）或 str（chunk）
            if isinstance(evt, dict):
                events.append({"type": evt.get("type", "?"), "data_keys": list(evt.keys())})
            else:
                chunks.append(str(evt))
    except Exception as e:
        elapsed = int((time.time() - t0) * 1000)
        return {
            "ok": False,
            "elapsed_ms": elapsed,
            "provider": provider,
            "model": model,
            "error": f"{type(e).__name__}: {e}",
            "trace": traceback.format_exc(limit=5),
        }
    elapsed = int((time.time() - t0) * 1000)

    full = "".join(chunks)
    ok = bool(full) and len(full) >= 1
    # 检查流里有没有出现 "2" 或类似答案（不严格，仅作 sanity）
    has_number_2 = "2" in full
    print(f"    {'PASS' if ok else 'FAIL'}  ({elapsed}ms)  chunks={len(chunks)} events={len(events)} has_2={has_number_2}")
    print(f"    text={full[:80]!r}")
    return {
        "ok": ok,
        "elapsed_ms": elapsed,
        "provider": provider,
        "model": model,
        "chunks": len(chunks),
        "events": len(events),
        "text": full,
        "has_number_2": has_number_2,
    }


# ──────────────────────────── main ────────────────────────────
def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--provider", default=None, help="强制指定 provider（如 deepseek）")
    p.add_argument("--model", default=None, help="强制指定 model")
    p.add_argument("--skip-agent", action="store_true", help="仅跑工具直调，跳过 LLM 调用")
    args = p.parse_args()

    provider = args.provider or _pick_provider()
    print(f"Real API smoke  ·  provider={provider or '(none)'}")
    print(f"  python: {sys.version.split()[0]}  ·  cwd: {os.getcwd()}")

    results: Dict[str, Any] = {"provider": provider, "model": args.model}

    # ── B 永远跑（不需要 LLM） ──
    results["tools"] = smoke_tools_direct()
    _save_artifact("tools", results["tools"])

    # ── A / C 需要 LLM ──
    if args.skip_agent:
        print("\n[--skip-agent] 跳过 LLM 调用")
    elif not provider:
        print("\n[SKIP] 未检测到任何 LLM_API_KEY_*，跳过 A / C")
        print("       至少设置一个：OPENAI_API_KEY / DEEPSEEK_API_KEY / QWEN_API_KEY / MINIMAX_API_KEY ...")
    else:
        # import agent 时会触发 provider/model 解析，这里强制覆盖一次
        os.environ["MODEL_PROVIDER"] = provider
        if args.model:
            os.environ["MODEL_NAME"] = args.model

        results["agent_hello"] = smoke_agent_hello(provider, args.model or "(default)")
        _save_artifact("agent_hello", results["agent_hello"])

        results["agent_stream"] = smoke_agent_stream(provider, args.model or "(default)")
        _save_artifact("agent_stream", results["agent_stream"])

    # ── 汇总 ──
    print("\n" + "─" * 60)
    print("Summary:")
    overall_ok = True
    for stage in ("tools", "agent_hello", "agent_stream"):
        r = results.get(stage)
        if not r:
            continue
        status = "PASS" if r.get("ok") else "FAIL"
        if not r.get("ok"):
            overall_ok = False
        ms = r.get("elapsed_ms", "?")
        print(f"  {stage:15s}  {status}  ({ms}ms)")
    print("─" * 60)
    print(f"Artifacts: evals/runs/<latest>_real_smoke/*.json")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
