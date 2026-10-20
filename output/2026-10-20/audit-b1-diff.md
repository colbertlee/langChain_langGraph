# audit-b1-diff
---
scope: ai_agent/**/*.py（runtime=业务代码；dev=业务+tests/）
decl_sources: requirements.txt, requirements-dev.txt, pyproject.toml[dev]

## 声明总览

| pip_name | spec | 来源 |
| --- | --- | --- |
| `akshare` | `>=1.16.0` | requirements-dev.txt |
| `argcomplete` | `>=3.1"` | pyproject.toml[dev] |
| `chromadb` | `~=0.4.0` | requirements.txt |
| `duckduckgo_search` | `~=6.1.7` | requirements.txt |
| `fastapi` | `~=0.116.0` | requirements.txt |
| `faster_whisper` | `~=1.0.3` | requirements.txt |
| `httpx` | `~=0.27.0` | requirements.txt |
| `ipython` | `~=8.20.0` | requirements-dev.txt |
| `ipython` | `>=8.20` | pyproject.toml[dev] |
| `jmespath` | `~=1.0.0` | requirements.txt |
| `langchain` | `~=0.2.0` | requirements.txt |
| `langchain_chroma` | `~=0.1.0` | requirements.txt |
| `langchain_community` | `~=0.2.0` | requirements.txt |
| `langchain_openai` | `~=0.1.0` | requirements.txt |
| `langchain_text_splitters` | `~=0.2.0` | requirements.txt |
| `matplotlib` | `~=3.7.0` | requirements.txt |
| `mypy` | `~=1.8.0` | requirements-dev.txt |
| `mypy` | `>=1.8` | pyproject.toml[dev] |
| `numpy` | `~=1.26.0` | requirements.txt |
| `opentelemetry_api` | `~=1.27.0` | requirements.txt |
| `pandas` | `~=2.1.0` | requirements-dev.txt |
| `pillow` | `~=10.4.0` | requirements.txt |
| `prometheus_client` | `~=0.21.0` | requirements.txt |
| `psutil` | `~=5.9.0` | requirements.txt |
| `pytesseract` | `~=0.3.10` | requirements.txt |
| `pytest` | `~=8.0.0` | requirements-dev.txt |
| `pytest` | `>=8.0` | pyproject.toml[dev] |
| `pytest_asyncio` | `~=0.23.0` | requirements-dev.txt |
| `pytest_asyncio` | `>=0.23` | pyproject.toml[dev] |
| `pytest_cov` | `~=4.1.0` | requirements-dev.txt |
| `pytest_cov` | `>=4.1` | pyproject.toml[dev] |
| `pytest_mock` | `~=3.12.0` | requirements-dev.txt |
| `pytest_mock` | `>=3.12` | pyproject.toml[dev] |
| `pytest_timeout` | `~=2.3.0` | requirements-dev.txt |
| `python_dotenv` | `~=1.0.0` | requirements.txt |
| `python_multipart` | `~=0.0.9` | requirements.txt |
| `pyyaml` | `~=6.0.2` | requirements.txt |
| `requests` | `~=2.31.0` | requirements.txt |
| `respx` | `~=0.21.0` | requirements-dev.txt |
| `ruff` | `~=0.3.0` | requirements-dev.txt |
| `ruff` | `>=0.3` | pyproject.toml[dev] |
| `sentence_transformers` | `~=2.7.0` | requirements.txt |
| `serpapi` | `~=0.1.0` | requirements.txt |
| `sse_starlette` | `~=2.4.1` | requirements.txt |
| `uvicorn` | `~=0.27.0` | requirements.txt |
| `webrtcvad` | `~=2.0.10` | requirements.txt |

## 运行时候选可清理（建议逐项裁决）

| pip_name | spec | 来源 | 证据（grep 验证） |
| --- | --- | --- | --- |
| `sse_starlette` | `~=2.4.1` | requirements.txt | 整个 ai_agent/** 无 `import sse_starlette` 或别名命中；建议二次 grep 确认（已用 Grep 工具交叉验证） |
| `python_multipart` | `~=0.0.9` | requirements.txt | 整个 ai_agent/** 无 `import python_multipart` 或别名命中；建议二次 grep 确认（已用 Grep 工具交叉验证） |

## dev 配置项（仅供说明，不建议清理）

| pip_name | 用途 |
| --- | --- |
| `pytest_asyncio` | pytest.ini 中 `asyncio_mode=auto` 即生效，无需 import |
| `pytest_cov` | CLI 调用：`--cov=.` 由 pytest 加载；插件入口不是源码 import |
| `pytest_mock` | fixture 由 pytest 注入；tests/ 里常见 `mocker` fixture |
| `pytest_timeout` | 装饰器 `@pytest.mark.timeout`；无源码 import |
| `ruff` | CLI 工具；不在运行时被 import |
| `mypy` | CLI 工具；不在运行时被 import |
| `ipython` | 可选 shell；可在 `cli.py` 间接引用 |

## 使用但未声明（运行时 import）

| import | 证据路径（最多 3 条） | 备注 |
| --- | --- | --- |
| `langchain_core` | `agent.py`, `agent_tool_router.py`, `agent_workers.py` | 由 `langchain` 拉入；通常无需单独声明 |
| `langgraph` | `agent.py`, `agent.py`, `agent_workers.py` | 由 `langchain` / `langgraph-checkpoint-sqlite` 拉入 |
| `pydantic` | `api.py`, `app.py`, `llm_minimax.py` | 由 FastAPI / langchain 拉入 |
| `starlette` | `observability/prom_http_metrics.py`, `observability/prom_http_metrics.py` | 由 FastAPI 拉入 |
| `whisper` | `audio_pipeline.py` | ⚠ 真未声明：需补到 requirements.txt |

## 裁决建议（请逐项确认 Y/N）

- **Y 删**：运行时未使用 + 不被任何间接依赖强依赖。
- **N 留**：属于间接依赖（如 `tokenizers` 被 `sentence_transformers` 强依赖）；或用于 `pyproject.toml` 配置项。
- **补声明**：使用但未声明 → 加到 `requirements.txt` 或写「运行时不直接 import 但需要部署」。

## 不要做（边界）

- 不直接删 `requirements*.txt` 任何行；本报告是「候选清单」，由用户裁决。
- `evals/` `docs/` `knowledge_base/` `package/` `data/` 下的 import 不计入使用证据。
- 内部模块名（`ai_agent.*`）按 `py-modules` 白名单识别，不算外部依赖。
- `mcp[cli]` / `[standard]` 这类 extras 按父名解析（`uvicorn` 而非 `uvicorn[standard]`）。
- dev 依赖的「未使用」≠「可清理」：pytest_asyncio/cov/mock/timeout 都是 pytest 插件入口。
