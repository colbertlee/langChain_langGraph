# SPEC · 后端依赖栈与代码 API 对齐（langchain 升级 + CI/Docker 工具链）

> 状态：**规格书，未开工**。所有"实测"均为 2026-10-20 在 PR #15 CI run 39442622936 与本地 venv 的真实输出。
> 前置：PR #15 已 squash 合并（`68355d2`），前端 3 项检查已绿，本规格只处理后端 2 项红 + 1 项遗留。

# ① Role & Context

生产代码与依赖钉版存在**根本矛盾**：

- [agent.py L24](../ai_agent/agent.py) 模块级 `from langchain.agents import create_agent` —— `create_agent` 是 **langchain 1.x API**
- [requirements.txt L12](../ai_agent/requirements.txt) 钉 `langchain~=0.2.0`
- **本地 venv 实测**（langchain 0.2.17）：`ImportError: cannot import name 'create_agent' from 'langchain.agents'`
  → 即本机 agent.py 当前也导不进来（除非运行在其它解释器，**需确认**）
- CI 实测（run 39442622936）：Backend Tests 报同一 ImportError + `NameError: name 'respx' is not defined`（2 个测试文件）；Docker Build (backend) 报 webrtcvad 编译缺 `stdlib.h`、pyreqwest-impersonate 链接缺 `Scrt1.o`

目标：让 **CI 的 Backend Tests + Docker Build (backend) 转绿**，且应用可真实启动。

# ② Tech Stack

| 包 | 本地 venv 实测 | requirements 钉版 | 目标 |
|---|---|---|---|
| langchain | 0.2.17 | `~=0.2.0` | **1.x**（含 `langchain.agents.create_agent`）|
| langchain-core | 0.2.43 | 未钉（transitive）| 与 langchain 1.x 兼容线 |
| langchain-openai | 0.1.25 | `~=0.1.0` | 1.x 兼容线 |
| langchain-community / chroma / text-splitters | 未查 | `~=0.2.0 / ~=0.1.0 / ~=0.2.0` | 随主栈对齐 |
| langgraph | **1.2.11**（已是新线）| 未钉 | 不动 |
| chromadb | 未查 | `~=0.4.0` | 先不动，冲突再议 |

- Python：Docker 镜像 `3.11-slim`；CI `setup-python 3.11`；本地 venv 版本**待确认**
- 开工第一步必须 `pip index versions langchain` 实测 dist-tags，**禁止凭记忆写版本号**

# ③ Detailed Requirements

- **R0 前置盘点（只读）**：grep 全仓 `from langchain` / `import langchain` 的**全部** import 点与所用符号，列出 0.2→1.x 的 breaking 清单（重点：`agents`/`chains`/`callbacks` 模块重组）。
- **R1 主升级**：requirements.txt 的 langchain 栈整体升到 1.x 兼容组合；`pip --dry-run` 官方源验证可解后才落盘。
- **R2 respx**：ci.yml 的 backend-tests 增加 `pip install -r requirements-dev.txt`（respx~=0.21.0 已在其中 L10，httpx~=0.27 兼容**需实测**）。
- **R3 Docker 工具链**：
  - ai_agent/Dockerfile apt 列表加 `libc6-dev`（webrtcvad sdist 编译需要）
  - `duckduckgo-search~=6.1.7` 三选一，**先验证再定**：
    a) 降 `~=4.4.1`（纯 Python，无 Rust 依赖；需确认 [search_tool.py](../ai_agent/v21_tools/search_tool.py) 的 `DDGS` 用法兼容）
    b) 镜像装 Rust（重，不推荐）
    c) 移出 requirements（search_tool.py 若有 import 守卫则优雅降级，**需 Read 确认**）
- **R4 回归**：全量 pytest + `python -c "import agent"` 冒烟 + 应用启动冒烟。

# ④ Edge Cases & Failure Recovery

| 场景 | 期望行为 |
|---|---|
| langchain 1.x 下 `ChatOpenAI` 构造参数变化 | R0 清单里逐符号核对，改代码前先列 diff 提案 |
| langchain-chroma 无 1.x 兼容版 | 停止，报告兼容矩阵，交用户裁决（可能需换 vectorstore 接法）|
| respx 0.21 与 httpx 0.27 冲突 | pip dry-run 报错即回退：respx 升 0.22 线（实测后再定）|
| duckduckgo-search 4.4.x 与 6.x API 差异 | 跑 search_tool 相关测试；失败则改选 c 方案 |
| 本地 venv 升级破坏用户正在跑的环境 | 先 `pip freeze > requirements.lock.bak`；或新建 `.venv-v2`，不动原 venv |
| 升级后 create_agent 签名不匹配（如 `system_prompt=` 参数）| 以 langgraph/langchain 1.x 官方签名为准，逐调用点修（agent.py 共 4 处：L606/L764/L940 + L24 import）|

# ⑤ Code Quality & Style

- 版本号一律 `pip index versions` 实测后写入，禁止编造
- 每个 requirements 改动附一行注释说明**证据来源**（CI run id / PyPI 实测）
- 不动前端任何文件；不动 E2E 业务断言（13 failed/4 passed 为独立工作项）
- 拆分提交：R1+R0 一个 PR，R2+R3 可并入；R4 结果写进 PR 描述

# ⑥ Test & Verification

| # | 命令/检查 | 判据 |
|---|---|---|
| T1 | `pip install --dry-run -r requirements.txt`（官方源）| exit 0（若本地超时，以 CI 为准并在 PR 注明）|
| T2 | `python -c "import agent"` | 无 ImportError |
| T3 | `pytest -m "not slow and not integration"` | 全绿（含原 respx/create_agent 4 个收集错误消失）|
| T4 | `docker build ai_agent/` | webrtcvad/pyreqwest 编译通过 |
| T5 | CI `Backend Tests` + `Docker Build (backend)` | **转绿**（最终裁判）|
| 反证 | 若 T2 仍报 create_agent ImportError | 目标版本判断错误 → 停，重查 dist-tags，不得继续 |

## 不要做

- 不在本任务里修 Frontend E2E 的 13 个业务断言
- 不顺手升级 chromadb / torch / sentence-transformers 大版本
- 不重写 agent.py 的业务逻辑（只允许 API 签名适配的最小改动）
- 不在未跑 T2/T3 前宣称"升级完成"

---

## 附：当前仓库遗留（与本规格无关，需用户裁决）

1. **本地 master 历史分叉**：PR #15 以 squash 合并（origin `68355d2`），本地 master 仍含原始 3 提交 + 你自己的 2 个新提交（`08ef623`/`01981d4`），领先 5 落后 1。内容差异干净（仅你的工作）。建议 `git rebase --onto origin/master 8190460 master` 整理，**由你执行或明确授权**。
2. **gitee/master 停在 `75345c7`**：与 origin 已分叉（squash 导致），同步需 force-push 或 merge，未擅动。
3. E2E 13 个业务断言失败：独立工作项，未立规格。
