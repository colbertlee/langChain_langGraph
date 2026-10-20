# AI Agent 用户使用手册

> 适用版本:**v2.5.0**(LangChain × LangGraph AI Agent 终端用户手册)
>
> 这份文档的目标读者是 **直接使用本系统的最终用户**,而非开发者。如果你只想把 Agent 跑起来、让它帮你做事,看这份就够了;API / 部署 / 二次开发请看 [README.md](README.md) / [docs/API.md](docs/API.md) / [OPERATIONS.md](OPERATIONS.md)。

---

## 目录

- [1. 我能用 AI Agent 做什么?](#1-我能用-ai-agent-做什么)
- [2. 三种打开方式(选一个就行)](#2-三种打开方式选一个就行)
  - [2.1 React 控制台(推荐)](#21-react-控制台推荐)
  - [2.2 单文件 HTML 主界面(最轻量)](#22-单文件-html-主界面最轻量)
  - [2.3 命令行 CLI(极客向)](#23-命令行-cli极客向)
  - [2.4 桌面二进制(给最终用户)](#24-桌面二进制给最终用户)
  - [2.5 Docker 一键](#25-docker-一键)
- [3. 第一次使用:5 分钟跑通](#3-第一次使用5-分钟跑通)
  - [3.1 准备 API Key](#31-准备-api-key)
  - [3.2 选模型](#32-选模型)
  - [3.3 第一次对话](#33-第一次对话)
- [4. 进阶玩法](#4-进阶玩法)
  - [4.1 切换模型 Provider](#41-切换模型-provider)
  - [4.2 上传文件,做 RAG 文档问答](#42-上传文件做-rag-文档问答)
  - [4.3 跨会话长期记忆](#43-跨会话长期记忆)
  - [4.4 工具调用可视化](#44-工具调用可视化)
  - [4.5 思维链(CoT)折叠面板](#45-思维链cot折叠面板)
  - [4.6 Prompt 版本管理](#46-prompt-版本管理)
  - [4.7 HITL 审批中心(危险操作人工把关)](#47-hitl-审批中心危险操作人工把关)
  - [4.8 多 Agent Supervisor](#48-多-agent-supervisor)
  - [4.9 音频 / 语音输入](#49-音频--语音输入)
  - [4.10 续生成(checkpoint resume)](#410-续生成checkpoint-resume)
- [5. Web 控制台八个页面速查](#5-web-控制台八个页面速查)
- [6. 常见任务示例](#6-常见任务示例)
- [7. 错误码与排错速查](#7-错误码与排错速查)
- [8. 数据与隐私](#8-数据与隐私)
- [9. 我想卸载 / 重置](#9-我想卸载--重置)

---

## 1. 我能用 AI Agent 做什么?

AI Agent 是一个 **可对话、可调用工具、可记忆、可审批** 的本地 Agent 平台。典型场景:

| 我想做的事 | 用什么能力 | 见 |
|---|---|---|
| 跟 AI 聊天 / 写作 / 翻译 / 总结 | 基础对话(11 家 LLM 任选) | [§3](#3-第一次使用5-分钟跑通) |
| 让 AI 答不上来时,自动查 ETF / 股票 / 天气 / 搜索 | 工具调用(`get_etf_price` / `web_search` / `get_weather` …) | [§4.4](#44-工具调用可视化) |
| 给 AI 一份文档,让它基于文档回答问题 | RAG 知识库(上传 → 索引 → 检索) | [§4.2](#42-上传文件做-rag-文档问答) |
| 让 AI 记住"我喜欢 markdown 表格",下次直接用 | 长期记忆(`/api/memory/remember`) | [§4.3](#43-跨会话长期记忆) |
| 删文件 / 写文件 / 跑 shell 之前强制让我确认 | HITL 人机协同 | [§4.7](#47-hitl-审批中心危险操作人工把关) |
| 复杂任务自动拆给"研究员 / 工程师 / 评审" | Supervisor 多 Agent | [§4.8](#48-多-agent-supervisor) |
| 录音后让 AI 听写 | 音频转写(Whisper) | [§4.9](#49-音频--语音输入) |
| 切换不同的 Prompt 版本 / 模型做实验 | Prompt 工程 + 模型切换 | [§4.6](#46-prompt-版本管理) |
| 想知道 AI 在背后做了什么 | 事件流 / Trace / Prometheus 指标 | [§5 /insights](#5-web-控制台八个页面速查) |

---

## 2. 三种打开方式(选一个就行)

### 2.1 React 控制台(推荐)

```
浏览器 → http://localhost:5173 (开发模式)
浏览器 → http://localhost:8000 (Docker / 桌面 / 生产模式)
```

- 顶部状态灯:绿色 = 后端可达,红色 = 后端未启动
- 三个主路由:
  - `/chat` —— 流式对话 + 工具调用可视化 + 思维链折叠
  - `/admin?tab=agents|tools|settings|approval|prompts|memory` —— 五个 Tab 聚合管理
  - `/insights` —— Token 用量 / 错误率 / Trace 列表
- 旧链接(`/agents` `/tools` `/approval` `/prompts` `/memory` `/settings` `/observability`)会自动重定向到新路由

> 如果你只想用 AI Agent,**用这个就对了**。

### 2.2 单文件 HTML 主界面(最轻量)

不需要 Node,只要浏览器:

```bash
cd ai_agent/web
python -m http.server 8765
# 浏览器打开 http://localhost:8765/
```

5 个 tab:设置 / 工具 / 记忆 / 计划 / 运维/观测。**优点**:零依赖、加载快;**缺点**:UI 比 React 控制台朴素。

### 2.3 命令行 CLI(极客向)

不需要浏览器:

```bash
cd ai_agent
python main.py
# 进入 REPL
你: 你好
你: 查 510300 价格
你: exit
```

CLI 内置命令:`exit` / `quit` / `clear` / `help` / `tools` / `history` / `version`。

### 2.4 桌面二进制(给最终用户)

不想装 Python?下载桌面包解压即用:

- **Windows**:`package\windows\` → 双击 `install.bat` → 填 `.env` → 双击 `run.bat` 启 CLI / `run-web.bat` 启 Web 服务
- **Linux / macOS**:`package/linux/` → `chmod +x ai-agent install.sh run.sh run-web.sh` → `./install.sh` → `./run.sh` 或 `./run-web.sh`

桌面包含完整 Python 运行时(~470 MB),**无需装任何依赖**。

### 2.5 Docker 一键

```bash
docker pull ghcr.io/colbertlee/ai-agent-console:2.5.0
docker run -d -p 8000:8000 -e OPENAI_API_KEY=sk-xxx ghcr.io/colbertlee/ai-agent-console:2.5.0
# 浏览器打开 http://localhost:8000
```

或本仓库根目录 `docker compose up -d --build`(自动构建前后端)。

---

## 3. 第一次使用:5 分钟跑通

### 3.1 准备 API Key

任选一家的 Key 填到 `ai_agent/.env`:

| Provider | 拿 Key 的地方 | 推荐场景 |
|---|---|---|
| **DeepSeek** | platform.deepseek.com | 国产首选,性价比最高 |
| **通义千问 (Qwen)** | dashscope.aliyun.com | 中文最强 |
| **智谱 GLM** | open.bigmodel.cn | 推理模型 Z1 |
| **Kimi (Moonshot)** | platform.moonshot.cn | 长上下文 128K |
| **豆包 (Doubao)** | volcengine.com(火山方舟 ARK) | 字节系 |
| **腾讯混元** | cloud.tencent.com | 腾讯系 |
| **OpenAI** | platform.openai.com | 全球 |
| ...共 11 家 | 见 [README §4.2](README.md#42-支持的-provider11-家) | |

```env
# 至少填一个。推荐 DeepSeek + Qwen 双 Provider 作为兜底。
DEEPSEEK_API_KEY=sk-...
QWEN_API_KEY=sk-...
```

### 3.2 选模型

- **Web 控制台**:`/admin?tab=settings` → "模型下拉"按 Provider 分组显示,未配置 Key 的 Provider 灰显
- **API**:`POST /api/model/switch` body `{"provider":"deepseek","model":"deepseek-chat"}`
- **命令行**:在 Web 设置面板选好即可,CLI 共享同一份配置

### 3.3 第一次对话

```bash
cd ai_agent
python app.py   # 监听 http://localhost:8000
# 浏览器打开 http://localhost:8000/
```

在 Chat 页输入"你好",看到流式输出 = 跑通。

---

## 4. 进阶玩法

### 4.1 切换模型 Provider

**Web 控制台**:`/admin?tab=settings` → 模型下拉(按 Provider 分组)→ 保存。

**主备自动切换**(生产推荐):

```python
# python -c
from ai_agent.agent import AIAgent
a = AIAgent()
a.set_primary_standby(
    primary={"provider": "deepseek", "model": "deepseek-chat"},
    standbys=[
        {"provider": "qwen", "model": "qwen-turbo"},
        {"provider": "doubao", "model": "doubao-pro-32k"},
    ],
    enable_warmup=True,  # 后台预热 Standby,故障秒级切换
)
```

主 Provider 不可达时,**自动按 standbys 顺序切换**,前端 UI 会显示"已切换到 X"。

### 4.2 上传文件,做 RAG 文档问答

**第 1 步 · 上传**:

```bash
curl -X POST http://localhost:8000/api/upload -F "file=@manual.pdf"
# → {"name":"manual.pdf","url":"/api/files/manual.pdf"}
```

Web 控制台:Chat 页面附件按钮 → 选文件 → 自动上传。

**第 2 步 · 索引**(默认 Web 上传时自动索引;若用 API 上传,需手动):

```bash
curl -X POST http://localhost:8000/api/rag/index_file \
  -H "Content-Type: application/json" \
  -d '{"file_id":"manual.pdf"}'
```

**第 3 步 · 提问**:

```
你: 用户如何重置密码?
Agent: (基于 manual.pdf 的章节回答,并引用原文)
```

**进阶**:
- 切换 Embedding:在 `.env` 设 `EMBEDDING_MODEL_TYPE=zhipu`(智谱)或 `minimax` / `jina`(免费)
- 索引存放:`ai_agent/chroma_db/`,可整体备份
- 强制只答知识库:在 `/admin?tab=prompts` 的 System Prompt 加 "若知识库无相关内容,回答 '未找到相关信息',不要编造"

### 4.3 跨会话长期记忆

```bash
# 让 Agent 记住偏好
curl -X POST http://localhost:8000/api/memory/remember \
  -H "Content-Type: application/json" \
  -d '{"content":"我喜欢 markdown 表格"}'
```

下次任意会话都会自动召回:

```
你: 今天几只 ETF 表现
Agent: (输出 markdown 表格,因为记忆里有"偏好 markdown 表格")
```

**查看 / 删除**:
- `GET /api/memory/list` —— 列出所有记忆
- `DELETE /api/memory/{id}` —— 删除单条
- Web 控制台:`/admin?tab=memory` 一键查看

**四类记忆**:WORKING(当前交互)/ EPISODIC(会话片段)/ SEMANTIC(知识沉淀,向量检索)/ PROCEDURAL(操作流程)。

### 4.4 工具调用可视化

AI Agent 不只是"对话",还能**自动调用工具**。在 Chat 页,每条 AI 消息下方会出现**彩色 pill**:

| 工具 | 触发条件 |
|---|---|
| `get_etf_info` / `get_etf_price` | 你问"查 510300 价格" |
| `compare_etfs` | 你说"对比 510300 和 510500" |
| `web_search` | 你问"今天 AI 新闻" |
| `get_weather` | "北京今天天气" |
| `query_knowledge_base` | 你已上传文档并问相关问题 |
| `read_file` / `write_file` | "读 README.md" / "把这段文字写到 notes.txt" |
| `run_code` / `python_interpreter` | "算 2^10" / "写个快排序" |
| `github_search` | "找 Star 最多的 Python 项目" |
| `generate_chart` | "生成 ETF 走势图" |

每个 pill 点开能看到:
- 工具名
- 入参
- 耗时
- 返回摘要

**安全限制**:
- 文件工具:只允许相对路径,`..` 和绝对路径会被拦截
- 代码执行:AST 白名单,只允许数学表达式(`run_code` 不允许 `import / exec / eval`)
- 危险命令:见 [§4.7 HITL](#47-hitl-审批中心危险操作人工把关)

### 4.5 思维链(CoT)折叠面板

当 Agent 输出 `## 思考 ## ...` 段落时,Web 控制台会自动**折叠成"💭 思考过程(点击展开)"**。不展开也能正常阅读回答;展开能看到推理过程。

可在 `/admin?tab=prompts` 关闭 CoT(回滚到 v1.0.0 无 CoT 版)。

### 4.6 Prompt 版本管理

`/admin?tab=prompts`:
- 看到当前激活版本(`default` 模板 `2.0.0` = CoT 注入版)
- 一键回滚到任意历史版本
- 适合场景:模型效果回归 → 切 v1.0.0 兜底;新版本验证 → 切 v2.0.0

User Prompt(`/api/user-prompts`)支持 few-shot + 导入导出,可团队共享模板。

### 4.7 HITL 审批中心(危险操作人工把关)

**核心场景**:Agent 想 `rm -rf` / 改生产配置 / 调用 `python_interpreter` 时,需要你**手动批准**才能继续。

`/admin?tab=approval` —— "审批中心"页面:

- 待审批卡片 = 高亮显示当前请求(工具名 / 参数 / 触发原因 / 风险等级)
- 按钮:`批准` / `拒绝` / `带修改批准`
- 决议写入历史(`/admin?tab=approval` 的"历史"Tab)

**配置策略**(`/api/hitl/policy`):

```bash
# 让 shell 类工具全部强制审批
curl -X POST http://localhost:8000/api/hitl/policy \
  -H "Content-Type: application/json" \
  -d '{"tool_pattern":"*shell*","action":"ASK"}'
```

策略含义:
- `PASS` —— 放行
- `ASK` —— 每次问(默认)
- `BLOCK` —— 直接禁止

**v2 slim 审批升级**:`/api/hitl/v2/pending` 列出 v2 风格的扁平待审批列表,与 `/api/chat/{request_id}/resume` 一致;审批后自动续生成,前端无需刷新。

### 4.8 多 Agent Supervisor

适合"复杂任务需要多角色协作"。

**触发方式**:把 `mode=supervisor` 加在请求体,或直接用专用端点:
```bash
curl -N -X POST http://localhost:8000/api/chat/supervisor/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"写一篇关于 ETF 的研究报告","session_id":"s-1"}'
```

**前端体验**:Chat 页会出现"agent_switch"事件提示,告诉你现在由哪个 Worker 执行任务(研究 / 代码 / RAG)。每个 Worker 独立加载工具,**最小授权原则**。

5 种模式(完整列表):
- `SUPERVISOR` —— 主 Agent 协调专业 Agent(v2.5.0 默认 + 推荐)
- `PARALLEL` —— 多 Agent 同时跑,取最优
- `SEQUENTIAL` —— 流水线
- `HIERARCHICAL` —— 多层 Agent 协同
- `FANOUT` —— 一任务分发给多 Agent 投票

v2.5.0 默认只暴露 SUPERVISOR + SEQUENTIAL 两类;其余模式保留配置入口,见 `ai_agent/multi_agent.py`。

### 4.9 音频 / 语音输入

```bash
# 转写音频文件
curl -X POST http://localhost:8000/api/audio/transcribe -F "file=@recording.wav"

# 实时流式识别(Web 控制台麦克风按钮)
ws://localhost:8000/api/audio/stream  # 浏览器 MediaRecorder
```

底层走本地 Whisper / Faster-Whisper;若未安装依赖,端点返回 `501`,不影响其他功能。

### 4.10 续生成(checkpoint resume)

如果对话中途你按了"停止生成"或 HITL 拒绝,Agent 会**把当前状态写入 SqliteSaver**。

- 列出可恢复点:`GET /api/checkpoints/list?session_id=s-1`
- 拉取某点状态:`GET /api/checkpoints/get?session_id=s-1&checkpoint_id=cp-xxx`
- 续生成:`GET /api/chat/{request_id}/resume`(HITL 审批后自动触发)

---

## 5. Web 控制台八个页面速查

| 路由 | 做什么 |
|---|---|
| `/chat` | 流式对话 + 工具调用 + 思维链 |
| `/admin?tab=agents` | Sub-Agent 管理 / preset 增删改查 |
| `/admin?tab=tools` | 已注册工具列表 + 启停 + Schema |
| `/admin?tab=settings` | Provider / 模型 / Embedding / 容错参数 |
| `/admin?tab=approval` | HITL 待审批 + 历史 + 策略 |
| `/admin?tab=prompts` | System / User Prompt 版本 + 回滚 |
| `/admin?tab=memory` | 长期记忆查看 + 删除 |
| `/insights` | Token 用量 / 错误率 / Trace 列表 / Prom 指标卡 |

旧链接(`/agents /tools /settings /approval /prompts /memory /observability`)自动 301 到新地址,**不会失效**。

---

## 6. 常见任务示例

### 任务 1 · 做客服 Agent(RAG 文档问答)

```bash
# 1. 上传文档
curl -X POST http://localhost:8000/api/upload -F "file=@./manual.pdf"

# 2. 加载到 RAG(自动索引,前端会自动处理)

# 3. 提问
你: 用户如何重置密码?
```

### 任务 2 · 做代码助手

```
你: 写一个快速排序,然后跑 100 个随机数组验证
Agent: (写代码 → 自动跑 → 验证)
```

### 任务 3 · 做金融分析师

```
你: 查 510300 的最新价格
Agent: (调用 get_etf_price)

你: 对比 510300 和 510500 近 30 天走势
Agent: (调用 compare_etfs)

你: 给我一份 159919 的投资分析报告
Agent: (调用 etf_analysis)
```

### 任务 4 · 做多 Agent 协作

走 Supervisor:`POST /api/chat/supervisor/stream`,Worker 内部自动拆解。

### 任务 5 · 做长期陪伴 / 个人助理

```bash
curl -X POST http://localhost:8000/api/memory/remember \
  -H "Content-Type: application/json" \
  -d '{"content":"我喜欢 markdown 表格"}'
```

### 任务 6 · 危险操作人机协同

```bash
# 配置:shell 类操作必须审批
curl -X POST http://localhost:8000/api/hitl/policy \
  -H "Content-Type: application/json" \
  -d '{"tool_pattern":"*shell*","action":"ASK"}'

# 然后 Agent 触发 shell 时:前端弹"审批中心"卡片
```

### 任务 7 · 多 Provider 自动容错

按 [§4.1](#41-切换模型-provider) 配置 `set_primary_standby` 即可。

### 任务 8 · A/B 测试 Prompt / 模型

```python
from ai_agent.ab_testing import ABTest
test = ABTest(name="prompt-v2", variants={"v1": "...", "v2": "..."})
test.run(question="...", n=100)
print(test.report())
```

---

## 7. 错误码与排错速查

| 错误现象 | 原因 / 修法 |
|---|---|
| "OPENAI_API_KEY not set" | `.env` 填入真 Key,或在 Web `/admin?tab=settings` 在线填 |
| "placeholder key" 导致 LLM 没初始化 | Key 是 `sk-xxx...` 占位符 → 设 `AI_AGENT_DISABLE_PLACEHOLDER_CHECK=0` 或填真 Key |
| 端口 8000 被占 | `PORT=9000 python app.py` |
| 模型下拉灰显 | 对应 Provider 没在 `.env` 配 Key |
| 切换模型不生效 | 调 `/api/model/switch` 或刷新 Web |
| 工具调用静默失败 | 看 Web 红色 🛡️ 横幅;查 `agent.log` |
| 全部 Provider 不可用 | 五层容错会触发降级;查 `/api/fail-log/summary` |
| 文件路径 `..` 被拦截 | 用相对路径;`read_file("README.md")` |
| `python_interpreter` 触发 HITL | 默认 `requires_approval=True`;审批即可 |
| Windows 桌面版中文乱码 | `run.bat` 已 `chcp 65001`,若仍乱码执行 `python -c "import sys; sys.stdout.reconfigure(encoding='utf-8')"` |
| macOS Gatekeeper 拦截桌面包 | `xattr -dr com.apple.quarantine ai-agent` |
| LLM 一直 timeout | 检查代理/防火墙;切 Provider;看 `/api/fail-log/summary` |

---

## 8. 数据与隐私

**全部默认本地,不依赖任何远程服务**(除你配置的 LLM Provider)。

| 数据 | 默认位置 | 是否上行 |
|---|---|---|
| 对话消息 | `ai_agent/context_memory.db`(SQLite) | ❌ |
| 长期记忆 | 同上,合并存储 | ❌ |
| RAG 向量库 | `ai_agent/chroma_db/` | ❌ |
| 上传文件 | `ai_agent/uploads/` | ❌ |
| 日志 | `ai_agent/agent.log` | ❌ |
| 失败日志 | `ai_agent/fail_log.db` | ❌ |
| 可观测事件 | `ai_agent/observability.db` | ❌ |

**唯一的上行流量**是你配置的 LLM Provider。**本项目不上传任何遥测、不收集任何 usage、不调用任何第三方分析**。

**API Key 安全**:
- 只保存在本地 `.env` 或 `/api/api-key` 调用后的内存中
- 不参与日志(`security.redact_output` 自动脱敏 `sk-` / `Bearer` / `password`)
- 前端 React 控制台不持有 Key,只持有 `provider:configured` 布尔

**可关闭项**:
| 关闭项 | 方法 |
|---|---|
| 可观测事件采集 | 不启动 `observability.py` 或调 `/api/context/performance/reset` |
| 工具调用日志 | `LOG_LEVEL=WARNING` |
| 失败日志持久化 | `FailLogRepository` 改用 `InMemory` backend |

**合规建议**:
- **GDPR / 个保法**:记忆支持 `DELETE /api/memory/{id}` 与 `/api/memory/forget`,可满足"被遗忘权"
- **数据出境**:LLM 请求会发到你配置的 Provider 服务器,**境内用户优先用 DeepSeek / Qwen / 智谱 / Kimi / 豆包** 等国内 Provider

---

## 9. 我想卸载 / 重置

| 形态 | 卸载方法 |
|---|---|
| Python 包 | `pip uninstall ai-agent` |
| Docker | `docker compose down -v`(**注意 `-v` 会清掉数据,先备份**) |
| 桌面包 | 直接删除整个 `package/windows/` 或 `package/linux/` 文件夹 |
| 重置数据(保留安装) | 删 `ai_agent/*.db`、`ai_agent/chroma_db/`、`ai_agent/uploads/`、`ai_agent/agent.log` |
| 仅清会话历史 | `POST /api/clear` 或 Web 控制台"清空对话"按钮 |

备份:
```bash
tar czf ai_agent_backup_$(date +%F).tar.gz ai_agent/*.db ai_agent/uploads ai_agent/chroma_db
```

恢复:
```bash
tar xzf ai_agent_backup_2026-09-08.tar.gz -C /path/to/new/install
```

---

## 相关文档

- 快速试玩(开发者向):[QUICKSTART.md](QUICKSTART.md)
- 后端完整文档(开发者向):[ai_agent/README.md](ai_agent/README.md) / [ai_agent/FEATURES_GUIDE.md](ai_agent/FEATURES_GUIDE.md)
- API 参考:[docs/API.md](docs/API.md)
- 运维 SOP:[OPERATIONS.md](OPERATIONS.md)
- 版本变更:[CHANGELOG.md](CHANGELOG.md) / [release_notes/v2.0.10.md](release_notes/v2.0.10.md) / [release_notes/v2.0.11-patch.md](release_notes/) (如有)