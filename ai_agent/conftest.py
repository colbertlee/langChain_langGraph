"""
P2-3 / P2-7 — pytest conftest.py（覆盖率门禁 + 共享 fixture）

作用：
  1. 把 ai_agent/ 加入 sys.path（让 from app import ... / from agent import ... 能跑通）
  2. 配置全局 fixture（如果后面要加 setUp 公共逻辑）
  3. 给 coverage 提供 omit/exclude 等公共规则（实际在 pyproject.toml）

历史背景：
  v2.x 重构（P0/P1/P2 系列）期间，agent.py 内部结构调整导致部分旧测试
  不兼容；P2-7 已全部修复（2024-Q4 收尾）：
    - test_app_spa_fallback.py    → 重写为「架构边界测试」
    - test_basic_endpoints.py     → 删除 TestStatic；增加 TestRoot JSON 断言
    - test_tools.py               → TestKnowledgeBase 改用 rag_service mock
    - test_upload.py              → 用 app._safe_filename + 真实端点测试
    - test_v2_slim_consistency.py → 静态断言改为 tools_registry 契约
    - test_v2_slim_stream_events.py → 静态断言支持 tool_start/tool_result/tool_end

  当前策略：所有测试默认全量跑（不再自动打 legacy 标记）。
  CI 命令：pytest（不带 -m "not legacy"）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让 from app import ... / from agent import ... 能跑通
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ─────────────── 全局 fixture ───────────────


@pytest.fixture(scope="session")
def ai_agent_root() -> Path:
    """ai_agent 根目录绝对路径。"""
    return _HERE


@pytest.fixture
def disable_llm_network(monkeypatch):
    """防止测试触发真实 LLM 调用（即使代码 bug 也不会泄漏 token）。"""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-disabled-in-test")
    monkeypatch.setenv("AI_AGENT_DISABLE_LLM", "1")
    yield
