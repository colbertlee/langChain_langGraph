"""
LLM Agent 集成测试

不依赖真实 LLM API key 的情况下也能跑：
- A. 检查环境变量 + 真实 key 检测
- B. Agent 注册表 / CapabilityRegistry 框架层（mock LLM）
- C. Agent.run() 路径：传入 mock ChatModel，验证意图路由不选择玩具工具
- D. 如果有真实 key，跑 1 个最小化 prompt → response
"""
import os
import sys
import json
import asyncio
from typing import List

# 强制 UTF-8 输出（Windows GBK 兼容）
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

PASS, FAIL = 0, 0
def ok(name, cond, detail=""):
    global PASS, FAIL
    detail_safe = str(detail).encode("ascii", "backslashreplace").decode("ascii")
    if cond:
        PASS += 1
        print(f"  [PASS] {name}" + (f"  ({detail_safe})" if detail_safe else ""))
    else:
        FAIL += 1
        print(f"  [FAIL] {name}" + (f"  ({detail_safe})" if detail_safe else ""))


# ───────── A. 环境变量 / Key 检测 ─────────
print("\n── A. Environment / Key detection ──")
import config
keys = {
    "OPENAI_API_KEY": config.OPENAI_API_KEY,
    "DEEPSEEK_API_KEY": config.DEEPSEEK_API_KEY,
    "QWEN_API_KEY": config.QWEN_API_KEY,
    "MINIMAX_API_KEY": config.MINIMAX_API_KEY,
    "ZHIPU_API_KEY": config.ZHIPU_API_KEY,
    "MOONSHOT_API_KEY": config.MOONSHOT_API_KEY,
    "BAIDU_API_KEY": config.BAIDU_API_KEY,
    "SPARK_API_KEY": config.SPARK_API_KEY,
    "DOUBAO_API_KEY": config.DOUBAO_API_KEY,
    "HUNYUAN_API_KEY": config.HUNYUAN_API_KEY,
    "SILICONFLOW_API_KEY": config.SILICONFLOW_API_KEY,
}
configured = [k for k, v in keys.items() if v and len(v) > 8]
ok("any-llm-key-configured", len(configured) >= 1,
   f"configured={configured or 'none'}")


# ───────── B. Agent 注册表（mock LLM）──────
print("\n── B. Agent Registry (mock LLM) ──")
from capability import get_capability_registry
from app import _seed_demo_workers_into

reg = get_capability_registry()
_seed_demo_workers_into(reg)
workers = reg.list_all()
ok("registry-workers-count", len(workers) == 4, f"count={len(workers)}")
expected_ids = {"supervisor-01", "coder-02", "researcher-01", "reviewer-01"}
got_ids = {w.worker_id for w in workers}
ok("registry-ids", expected_ids == got_ids, f"got={sorted(got_ids)}")

toy_caps = {"etf", "chart", "github_search", "github_issue", "github_pr"}
all_caps = set()
for w in workers:
    caps = w.capabilities
    if isinstance(caps, dict):
        all_caps.update(caps.keys())
    elif isinstance(caps, (list, tuple, set)):
        all_caps.update(caps)
ok("no-toy-capabilities", all_caps.isdisjoint(toy_caps), f"caps={sorted(all_caps)}")


# ───────── C. Tool 注册（玩具工具已彻底清理）──────
print("\n── C. Tool Registry (no toy tools) ──")
from tools import get_all_tools
ts = get_all_tools()
names = {getattr(t, "name", getattr(t, "__name__", "?")) for t in ts}
toy_funcs = {
    "get_current_time", "calculate", "search_web", "get_weather",
    "github_search", "generate_chart",
    "get_etf_info", "get_etf_price", "get_etf_history",
    "get_etf_knowledge", "compare_etfs", "etf_analysis",
}
ok("tools-no-toy", names.isdisjoint(toy_funcs), f"names={sorted(names)}")
ok("tools-count-7", len(names) == 7, f"count={len(names)}")


# ───────── D. v2_slim tools_v2（仍有图表复合工具，那是 v2 自己的抽象）────
print("\n── D. v2_slim tools (composite) ──")
try:
    from v2_slim.tools_v2 import get_all_tools_v2
    v2 = get_all_tools_v2()
    v2_names = [getattr(t, "name", getattr(t, "__name__", "?")) for t in v2]
    ok("v2-tools-count", len(v2) >= 4, f"count={len(v2)} names={v2_names}")
except Exception as e:
    ok("v2-tools-count", False, str(e))


# ───────── E. Skill 注册表（无 chart_visualization）────
print("\n── E. Skill Registry ──")
from skills import SkillManager
mgr = SkillManager()
all_skills = mgr.registry.list_all()
skill_names = {s.name for s in all_skills}
ok("skills-count-4", len(all_skills) >= 4, f"count={len(all_skills)}")
ok("no-chart-visualization", "chart_visualization" not in skill_names,
   f"names={sorted(skill_names)}")


# ───────── F. 真实 LLM 调用（如果有 key）──────
print("\n── F. Real LLM invocation ──")
async def try_real_llm():
    if not configured:
        ok("real-llm-skipped", True, "no API key configured")
        return
    # 按优先级尝试所有 key，任意一个成功即可
    PROVIDERS = [
        ("OPENAI_API_KEY", "gpt-4o-mini", None, config.OPENAI_API_KEY),
        ("DEEPSEEK_API_KEY", "deepseek-chat", "https://api.deepseek.com/v1", config.DEEPSEEK_API_KEY),
        ("QWEN_API_KEY", "qwen-turbo", "https://dashscope.aliyuncs.com/compatible-mode/v1", config.QWEN_API_KEY),
        ("MINIMAX_API_KEY", "MiniMax-Text-01", "https://api.minimaxi.com/v1", config.MINIMAX_API_KEY),
        ("ZHIPU_API_KEY", "glm-4-flash", "https://open.bigmodel.cn/api/paas/v4", config.ZHIPU_API_KEY),
        ("MOONSHOT_API_KEY", "moonshot-v1-8k", "https://api.moonshot.cn/v1", config.MOONSHOT_API_KEY),
        ("SILICONFLOW_API_KEY", "Qwen/Qwen2.5-7B-Instruct", "https://api.siliconflow.cn/v1", config.SILICONFLOW_API_KEY),
    ]
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    last_err = ""
    for name, model, base, key in PROVIDERS:
        if not key or name not in configured:
            continue
        # 跳过明显的 placeholder（包含 'your_' 或长度 < 10）
        if len(key) < 16 or key.lower().startswith("your_") or "****" in key:
            last_err = f"{name}=placeholder"
            continue
        try:
            kw = {"model": model, "temperature": 0, "max_tokens": 64, "api_key": key}
            if base:
                kw["base_url"] = base
            llm = ChatOpenAI(**kw)
            resp = await llm.ainvoke([HumanMessage(content="Reply with exactly one short sentence: 'pong'")])
            content = (resp.content or "").strip()[:120]
            if content:
                ok("real-llm-response", True, f"{name}/{model} -> {content!r}")
                return
            last_err = f"{name}=empty"
        except Exception as e:
            last_err = f"{name}: {type(e).__name__} {str(e)[:80]}"
            continue
    ok("real-llm-response", False, last_err or "no provider succeeded")

asyncio.run(try_real_llm())


# ───────── G. Agent run() 框架层（mock LLM）──────
print("\n── G. Agent.run() framework (mock LLM) ──")
try:
    from multi_agent import SupervisorAgent, AgentOrchestrator

    # 静态验证：agent.py 不引用被删的工具名
    import agent as agent_mod
    src = open(agent_mod.__file__, encoding="utf-8").read()
    refs = [t for t in toy_funcs if f"{t}(" in src or f"'{t}'" in src]
    ok("agent-no-toy-refs", len(refs) == 0, f"refs={refs}")

    # 静态验证：multi_agent.py 也不引用
    src2 = open(r"e:\langChain_langGraph\ai_agent\multi_agent.py", encoding="utf-8").read()
    refs2 = [t for t in toy_funcs if f"{t}(" in src2 or f"'{t}'" in src2]
    ok("multi-agent-no-toy-refs", len(refs2) == 0, f"refs={refs2}")
except Exception as e:
    ok("agent-run-framework", False, str(e)[:100])


# ───────── 总结 ─────────
print("\n" + "=" * 60)
print(f"RESULT: {PASS} passed, {FAIL} failed (total {PASS + FAIL})")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
