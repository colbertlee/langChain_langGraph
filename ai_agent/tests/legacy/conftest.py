"""
tests/legacy/conftest.py —— 把 legacy 测试在默认 pytest 收集时全部跳过。

原因：
- 这些测试引用已冻结的 MultiAgentOrchestrator / message_bus / auction 等模块，
  在 v2.0 slim 重构后仍会触发 asyncio 死锁（test_app_sse/ws/e2e 同样的根因）。
- v2 slim 已用 v2_slim.frozen_modules 把这些模块替换为 raise NotImplementedError，
  但 legacy 测试本身期望旧行为能跑通 → 冲突。

恢复方法：如需重跑 legacy 测试，明确指定该文件路径：
    pytest tests/legacy/test_xxx.py --no-header -v
或临时加环境变量 RUN_LEGACY_TESTS=1：
    RUN_LEGACY_TESTS=1 pytest tests/legacy/...
"""
import os

import pytest


_LEGACY_SKIP_REASON = (
    "legacy 测试在 v2.0 slim 默认跳过（RUN_LEGACY_TESTS=1 启用）。"
    "如需恢复，单独跑：pytest tests/legacy/<file> --no-header -v"
)


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LEGACY_TESTS") == "1":
        return  # 显式启用，不跳过
    skip_marker = pytest.mark.skip(reason=_LEGACY_SKIP_REASON)
    for item in items:
        # legacy 目录下的所有测试项
        if "tests/legacy/" in str(item.fspath) or "\\legacy\\" in str(item.fspath):
            item.add_marker(skip_marker)
