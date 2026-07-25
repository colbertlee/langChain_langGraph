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

    自动注入 fake API key，避免 web_ui.py 在 import 时调用真实 LLM。

    Usage:
        def test_openai_call(isolated_env):
            from langchain_openai import ChatOpenAI
            llm = ChatOpenAI()  # 不会真发请求
    """
    fake_keys = {
        "OPENAI_API_KEY": "sk-test-fake-key-for-tests-only",
        "ANTHROPIC_API_KEY": "sk-ant-test-fake-key",
        "SERPAPI_API_KEY": "test-serpapi-key",
        "DASHSCOPE_API_KEY": "test-dashscope-key",
        "OPENAI_API_BASE": "https://mock-openai.example.com/v1",
    }
    for k, v in fake_keys.items():
        monkeypatch.setenv(k, v)
    # 同时清理真实用户环境变量（如果有）
    yield


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


# ─────────────── 自动标记 ───────────────

def pytest_collection_modifyitems(config, items):
    """自动给测试加 marker 标签。

    - 含 'integration' 字样的 → @pytest.mark.integration
    - 含 'network' 字样的 → @pytest.mark.network
    - 慢测试（>2s）需要 @pytest.mark.slow 显式声明
    - legacy 目录下的 → @pytest.mark.legacy
    """
    integration_marker = pytest.mark.integration
    network_marker = pytest.mark.network
    legacy_marker = pytest.mark.legacy
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