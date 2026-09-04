"""
v2.0 slim — LEGACY 切换双路测试

验证：
1. LEGACY_MODE=False（默认）→ tools/memory/telemetry/multi_agent 走 v2 slim
2. LEGACY_MODE=True           → tools/memory/telemetry/multi_agent 走老实现

切换方式：通过环境变量 AIAgent_LEGACY=true 触发 config.LEGACY_MODE 重载。
本测试用 subprocess 隔离进程，避免污染主测试会话的 import cache。
"""
from __future__ import annotations

import os
import subprocess
import sys
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _run_in_subprocess(env_extra: dict, snippet: str) -> str:
    """在子进程中运行 Python snippet，返回 stdout。"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=60,
    )
    out = proc.stdout + "\n[STDERR]\n" + proc.stderr
    return out


# ============================================================
# 1. config.LEGACY_MODE 默认 False
# ============================================================

def test_legacy_mode_default_false():
    snippet = """
import config
print("LEGACY_MODE =", config.LEGACY_MODE)
"""
    out = _run_in_subprocess({}, snippet)
    assert "LEGACY_MODE = False" in out, out


def test_legacy_mode_via_env_true():
    snippet = """
import config
print("LEGACY_MODE =", config.LEGACY_MODE)
"""
    out = _run_in_subprocess({"AIAgent_LEGACY": "true"}, snippet)
    assert "LEGACY_MODE = True" in out, out


# ============================================================
# 2. LEGACY_MODE=False → v2 slim 路径
# ============================================================

def test_v2_slim_tools_count_when_not_legacy():
    snippet = """
import sys
sys.path.insert(0, r'%s')
from agent import _resolve_tools
tools = _resolve_tools()
print("TOOL_COUNT =", len(tools))
print("NAMES =", sorted(t.name for t in tools))
""" % str(ROOT)
    out = _run_in_subprocess({}, snippet)
    assert "TOOL_COUNT = 6" in out, out
    assert "file_ops" in out and "code_exec" in out


def test_v2_slim_memory_store_when_not_legacy():
    snippet = """
import sys
sys.path.insert(0, r'%s')
from agent import _resolve_memory_store
ms = _resolve_memory_store()
print("HAS_SHORT =", hasattr(ms, 'short'))
print("HAS_LONG =", hasattr(ms, 'long'))
print("TYPE =", type(ms).__name__)
""" % str(ROOT)
    out = _run_in_subprocess({}, snippet)
    assert "HAS_SHORT = True" in out
    assert "HAS_LONG = True" in out
    assert "TYPE = MemoryStore" in out


# ============================================================
# 3. LEGACY_MODE=True → 老实现路径
# ============================================================

def test_legacy_tools_count_when_legacy():
    """LEGACY 模式：tools 数 ≥ 6（老实现有 18+）。"""
    snippet = """
import sys
sys.path.insert(0, r'%s')
from agent import _resolve_tools
tools = _resolve_tools()
print("LEGACY_TOOL_COUNT =", len(tools))
""" % str(ROOT)
    out = _run_in_subprocess({"AIAgent_LEGACY": "true"}, snippet)
    # 老 tools.py 至少 6 个（实际上 18+）
    import re
    m = re.search(r"LEGACY_TOOL_COUNT = (\d+)", out)
    assert m, out
    n = int(m.group(1))
    assert n >= 6, f"LEGACY 工具数异常：{n}"


# ============================================================
# 4. telemetry 切换
# ============================================================

def test_telemetry_resolver_v2():
    snippet = """
import sys
sys.path.insert(0, r'%s')
from api import _resolve_monitor, _TELEMETRY_BACKEND
print("BACKEND =", _TELEMETRY_BACKEND)
m = _resolve_monitor()
s = m.get_stats()
print("HAS_COUNTERS =", 'counters' in s)
print("HAS_HISTOGRAMS =", 'histograms_summary' in s)
""" % str(ROOT)
    out = _run_in_subprocess({}, snippet)
    assert "BACKEND = v2_slim_telemetry" in out
    assert "HAS_COUNTERS = True" in out
    assert "HAS_HISTOGRAMS = True" in out


def test_telemetry_resolver_legacy():
    snippet = """
import sys
sys.path.insert(0, r'%s')
from api import _TELEMETRY_BACKEND
print("BACKEND =", _TELEMETRY_BACKEND)
""" % str(ROOT)
    out = _run_in_subprocess({"AIAgent_LEGACY": "true"}, snippet)
    assert "BACKEND = legacy_monitor" in out


# ============================================================
# 5. multi_agent 路由
# ============================================================

def test_multi_agent_router_v2_sequential():
    snippet = """
import sys
sys.path.insert(0, r'%s')
from v2_slim.multi_agent_router import create_sequential_agent
def step1(s): return {'scratchpad': {'a': 1}}
def step2(s): return {'scratchpad': {'b': 2}}
g = create_sequential_agent([step1, step2])
print("COMPILED =", g is not None)
""" % str(ROOT)
    out = _run_in_subprocess({}, snippet)
    assert "COMPILED = True" in out


def test_multi_agent_router_legacy_orchestrator():
    """LEGACY 模式下 get_orchestrator 不抛错（即使内部实现不可用也应返回 None 或实例）。"""
    snippet = """
import sys
sys.path.insert(0, r'%s')
from v2_slim.multi_agent_router import get_orchestrator
orch = get_orchestrator()
print("ORCH_NONE_OR_OBJ =", orch is None or hasattr(orch, 'run_workflow'))
""" % str(ROOT)
    out = _run_in_subprocess({"AIAgent_LEGACY": "true"}, snippet)
    assert "ORCH_NONE_OR_OBJ = True" in out


# ============================================================
# 6. 核心闭环：11 Provider 路由在两种模式下都必须可用
# ============================================================

@pytest.mark.parametrize("legacy", [False, True])
def test_provider_routes_independent_of_legacy_mode(legacy):
    env = {"AIAgent_LEGACY": "true"} if legacy else {}
    snippet = """
import sys
sys.path.insert(0, r'%s')
from agent import _build_provider_base_url
m = {
    'deepseek': 'https://api.deepseek.com/v1',
    'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    'minimax': 'https://api.minimax.chat/v1',
}
ok = all(_build_provider_base_url(k) == v for k, v in m.items())
print("ROUTES_OK =", ok)
""" % str(ROOT)
    out = _run_in_subprocess(env, snippet)
    assert "ROUTES_OK = True" in out


# ============================================================
# 7. run_workflow 统一入口
# ============================================================

def test_run_workflow_v2_frozen_modes():
    """v2 slim 模式下 parallel/hierarchical/fanout 应抛 NotImplementedError。"""
    snippet = """
import sys
sys.path.insert(0, r'%s')
from v2_slim.multi_agent_router import run_workflow
try:
    run_workflow('parallel', [])
    print("RAISED = False")
except NotImplementedError as e:
    print("RAISED = True")
    print("MSG =", str(e))
""" % str(ROOT)
    out = _run_in_subprocess({}, snippet)
    assert "RAISED = True" in out
    assert "Frozen in v2.0 slim" in out
