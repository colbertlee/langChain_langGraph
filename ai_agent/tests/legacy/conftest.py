"""tests/legacy 的 conftest（Day 4-5 清理）。

作用：
1. 给 legacy 目录下所有用例自动打 ``@pytest.mark.legacy``，
   默认排除（受 ``pyproject.toml`` 的 ``-m 'not legacy'`` 控制）。
2. 提供一个开关：环境变量 ``AI_AGENT_RUN_LEGACY=1`` 或显式
   ``pytest -m legacy`` 才跑这些用例。
"""
import os

import pytest


# 标记：仅当用户显式启用时才跑 legacy
_RUN_LEGACY = os.environ.get("AI_AGENT_RUN_LEGACY", "").lower() in ("1", "true", "yes")


def pytest_collection_modifyitems(config, items):
    """给 legacy 目录所有 case 自动打 ``legacy`` 标记。"""
    for item in items:
        if "tests/legacy" in str(item.fspath):
            item.add_marker(pytest.mark.legacy)


def pytest_configure(config):
    # 提示用户：legacy 默认被跳过
    if not _RUN_LEGACY:
        config._legacy_hint_emitted = True
