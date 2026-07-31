"""pytest 共享 fixtures 与全局配置。

## 当前测试统计

```
$ pytest tests/ --collect-only -q
13 tests collected in 0.95s
```

| 文件 | 测试数 |
|---|---|
| tests/test_basic_endpoints.py | 4 |
| tests/test_upload.py | 9 |

## 共享 fixtures

| Fixture | 作用域 | 作用 |
|---|---|---|
| `temp_dir` | function | 临时目录（自动清理） |
| `isolated_env` | function | 隔离环境变量 + 注入 fake API keys |
| `sample_messages` | function | 示例 OpenAI 格式消息序列 |
| `sample_upload_file` | function | 测试用文本文件（tmp_path） |
| `client` | function (per file) | FastAPI TestClient（test_upload / test_basic_endpoints 各自定义） |
| `isolated_middleware_budget` | function (autouse) | 把 `TokenUsageMiddleware` 的预算文件 + 全局状态重定向到 tmp_path，防跨测试污染 |

## pytest 内置 fixture（自动可用）

- `tmp_path` — 每个测试一个临时目录
- `monkeypatch` — 安全修改 env / attribute
- `caplog` — 捕获日志
- `capsys` — 捕获 stdout/stderr
- `pytester` — 测 pytest 插件（暂未用）
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import pytest


# ─────────────── 让 ai_agent/ 包内模块可被 import ───────────────
# 这样测试文件可以用 `import web_ui` 而不是 `from ..web_ui import`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────── 自定义 fixtures ───────────────


@pytest.fixture
def temp_dir() -> Iterator[str]:
    """临时目录，测试结束自动清理。

    Usage:
        def test_x(temp_dir):
            file_path = Path(temp_dir) / "x.txt"
            file_path.write_text("hi")
    """
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """隔离环境变量：测试中设置的值不会影响其他测试。

    PR4：转由 ``evals.harness._fixtures.isolated_env`` 提供；
    单一真相源（测试 + 评测一致），便于后续 PR 同步 fake LLM 等。
    """
    yield from _harness_isolated_env(monkeypatch)


@pytest.fixture
def sample_messages() -> list[dict]:
    """示例 OpenAI 风格消息序列。

    用法：测试 LLM prompt 模板 / context manager / 记忆等。
    """
    return [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "你好！有什么可以帮你？"},
        {"role": "user", "content": "介绍下 LangChain"},
    ]


@pytest.fixture
def sample_upload_file(tmp_path: Path):
    """测试用文本上传文件 fixture（写入 tmp_path，测试结束自动清理）。

    用法：TestClient.post('/api/upload', files={'file': (name, open(path))})
    """
    file_path = tmp_path / "test.txt"
    file_path.write_bytes(b"Hello world\nLine 2\n", encoding="utf-8")
    return file_path


# ─────────────── middleware 持久化状态隔离 ───────────────


@pytest.fixture
def isolated_middleware_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """隔离 ``TokenUsageMiddleware`` 的预算持久化状态，防跨测试污染。

    默认情况下，``TokenUsageMiddleware.__init__`` 在 ``daily_budget_usd`` /
    ``monthly_budget_usd`` 非空时把 ``~/.agent_middleware_budget.json`` 作为
    默认 ``budget_persist_path``，导致：

    - 同一日内 ``day_cost`` 跨测试持续累加（直到触发 ``TokenBudgetExceeded``）
    - ``_fired_alerts`` 集合不会被重置
    - 整文件 200+ 用例连续跑时，最后几条 alert 用例大概率挂

    本 fixture 把 ``$HOME`` 重定向到 ``tmp_path/.fake_home``（不与被测
    cwd 重叠），并 monkeypatch 已 import 的 ``agent_middleware.Path.home``
    做兜底。

    Usage:
        ``test_agent_middleware.py`` 顶部 ``from .conftest import isolated_middleware_budget``
        或显式声明。

    注意：本 fixture **不是 autouse**（autouse 会污染 ``tmp_path`` 之外的测试，
    如 ``test_tools.py::test_list_files_empty`` 依赖 ``tmp_path`` 下无子目录）。
    通过 ``tests/test_agent_middleware.py`` 顶部 ``pytestmark`` 自动应用：
        pytestmark = pytest.mark.usefixtures("isolated_middleware_budget")
    """
    fake_home = tmp_path / ".fake_home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))  # Windows 兼容

    # 兜底：直接 patch 已 import 的 agent_middleware.Path.home
    try:
        import agent_middleware as _am
        monkeypatch.setattr(_am.Path, "home", classmethod(lambda cls: fake_home))
    except ImportError:
        pass  # agent_middleware 未被任何测试 import，跳过

    yield
    # monkeypatch 自动还原


# ─────────────── 自动标记 ───────────────

def pytest_collection_modifyitems(config, items):
    """自动给测试加 marker 标签 + 自动应用 middleware 隔离 fixture。

    - 含 'integration' 字样的 → @pytest.mark.integration
    - 含 'network' 字样的 → @pytest.mark.network
    - 慢测试（>2s）需要 @pytest.mark.slow 显式声明
    - legacy 目录下的 → @pytest.mark.legacy
    - ``tests/test_agent_middleware.py`` 下的测试 → 自动使用
      ``isolated_middleware_budget`` fixture，隔离 ``$HOME`` 防预算污染
    """
    integration_marker = pytest.mark.integration
    network_marker = pytest.mark.network
    legacy_marker = pytest.mark.legacy
    middleware_marker = pytest.mark.usefixtures("isolated_middleware_budget")
    for item in items:
        # legacy 标记
        if "/legacy/" in item.nodeid:
            item.add_marker(legacy_marker)
        # integration 标记
        if "integration" in item.nodeid.lower():
            item.add_marker(integration_marker)
        # network 标记
        elif "network" in item.nodeid.lower():
            item.add_marker(network_marker)
        # middleware 隔离（仅作用于 test_agent_middleware.py）
        if "/test_agent_middleware.py" in item.nodeid:
            item.add_marker(middleware_marker)


# 显式注册 markers（消除 PytestUnknownMarkWarning）
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: 集成测试（可能慢、需要外部依赖）"
    )
    config.addinivalue_line(
        "markers", "network: 网络测试（需要真实 API）"
    )
    config.addinivalue_line(
        "markers", "slow: 慢测试（>2s）"
    )
    config.addinivalue_line(
        "markers", "legacy: 遗留测试（从 ai_agent/ 根目录迁移来）"
    )