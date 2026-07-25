# Agent 功能指南

本文档面向最终用户，快速了解和使用 AIAgent 的各项功能。

---

## 🎯 任务导向 · 我想做…

> 如果你不确定从哪里开始,看下面这个索引。每一个都给了**可直接复制粘贴的命令或对话示例**。

| 我想… | 用什么能力 | 关键文件 / API | 章节 |
|---|---|---|---|
| 做**客服 Agent**(文档问答) | RAG + 记忆 | `ai_agent/rag.py`、`/api/upload` | [§1 RAG 客服](#任务1-做客服-agentr--文档问答) |
| 做**代码助手**(写代码 / 解释代码) | Sandbox + 代码工具 | `ai_agent/sandbox.py`、`run_code` | [§2 代码助手](#任务2-做代码助手) |
| 做**金融分析师**(查 ETF / 对比 / 报告) | ETF 工具 + 容错 | `ai_agent/tools.py` ETF 部分 | [§3 金融分析](#任务3-做金融分析师) |
| 做**多 Agent 协作**(任务派发 / 评审) | Multi-Agent + 协商 | `ai_agent/multi_agent.py` | [§4 多 Agent](#任务4-做多-agent-协作) |
| 做**长期陪伴 / 个人助理**(跨会话记忆) | 长期记忆 + 上下文 | `memory_store` | [§5 长期记忆](#任务5-做个人助理) |
| 做**自动化工作流**(危险操作需审批) | HITL + 权限 | `human_in_loop.py`、`permission.py` | [§6 危险操作](#任务6-危险操作需人机协同) |
| 做**多 Provider 调度**(避免单点故障) | 五层容错 + 主备 | `llm_reliability.py` | [§7 容错调度](#任务7-多-provider-调度) |
| 做**A/B 测试 / 灰度**(对比两版 Prompt) | A/B + 自适应阈值 | `ab_testing.py` | [§8 A/B 测试](#任务8-ab-测试) |
| 做**可观测系统**(看 trace / 指标) | Observability + Prom | `observability.py` | [§9 可观测](#任务9-可观测) |

### 任务1:做客服 Agent(RAG 文档问答)

**适用场景**:你有产品文档 / FAQ / 政策文件,想做一个"问什么答什么"的客服。

**3 步走通**:
```bash
# 1. 上传文档
curl -X POST http://localhost:8000/api/upload -F "file=@./manual.pdf"
# 响应: {"name":"manual.pdf","url":"/api/files/manual.pdf"}

# 2. 加载到 RAG(告诉 Agent "请加载知识库")
你: 请加载 manual.pdf 进知识库

# 3. 提问
你: 用户如何重置密码?
Agent: (基于 manual.pdf 的章节回答,并引用原文)
```

**进阶**:
- 想换 Embedding?→ `EMBEDDING_MODEL_TYPE=zhipu`(智谱)或 `minimax` 或 `jina`
- 索引放哪里?→ `ai_agent/chroma_db/`,可整体备份
- 想强制只回答知识库内容?→ 在 System Prompt 加 "若知识库无相关内容,请回答 '未找到相关信息',不要编造"

---

### 任务2:做代码助手

**适用场景**:让 Agent 帮你写代码、解释代码、跑测试。

```python
# 让 Agent 解释一段代码
你: 这段代码是什么意思?  [粘贴代码]
Agent: (用 run_code 工具读 stdin,或直接分析)

# 让 Agent 跑测试
你: 跑一下 tests/test_foo.py
Agent: [tool_call: shell {"cmd": "pytest tests/test_foo.py -v"}]
       [tool_result: exit_code=0, ...]

# 写代码 + 自测
你: 写一个快速排序,然后跑 100 个随机数组验证
Agent: (写代码 → 自动跑 → 验证)
```

**安全设置**:
- `run_code` 走 AST 白名单,禁止 `import` / `exec` / `eval`(数学工具例外)
- `shell` 工具默认走 HITL 审批,见 [§6](#任务6-危险操作需人机协同)
- 沙箱:可启用 `ai_agent/sandbox.py` 把执行环境隔离在 subprocess

---

### 任务3:做金融分析师

**适用场景**:查 ETF 行情、对比、做组合分析。

```bash
# 单个 ETF
你: 查 510300 的最新价格
Agent: [tool_call: get_etf_price {"code":"510300"}]

# 对比
你: 对比 510300 和 510500 近 30 天走势
Agent: [tool_call: compare_etfs {"codes":["510300","510500"]}]

# 综合分析(含走势预测)
你: 给我一份 159919 的投资分析报告
Agent: [tool_call: etf_analysis {"code":"159919"}]
```

**数据源**:akshare(国内 ETF / A 股)、yahooquery(海外)。详见 `ai_agent/tools.py` ETF 部分。

---

### 任务4:做多 Agent 协作

**适用场景**:一个任务太复杂,需要"研究员 + 工程师 + 评审"分工。

```python
from multi_agent import AgentOrchestrator, WorkerAgent, Task

orchestrator = AgentOrchestrator(mode="SUPERVISOR")
orchestrator.register(WorkerAgent(name="researcher", capabilities=["web_search", "summarize"]))
orchestrator.register(WorkerAgent(name="engineer", capabilities=["code_run", "file_write"]))
orchestrator.register(WorkerAgent(name="reviewer", capabilities=["critique"]))

# 主 Agent 自动派发
result = orchestrator.run(goal="写一篇关于 X 的研究报告")
# → Supervisor 把"查资料"派给 researcher,把"写代码生成图表"派给 engineer,把"评稿"派给 reviewer
```

5 种模式详见 README §3.5:SUPERVISOR / PARALLEL / SEQUENTIAL / HIERARCHICAL / FANOUT。

---

### 任务5:做个人助理(长期记忆)

**适用场景**:Agent 能记住你 3 个月前说过"我喜欢 markdown 表格",今天直接用。

```bash
# 用户视角极简 API
curl -X POST http://localhost:8000/api/memory/remember \
  -H "Content-Type: application/json" \
  -d '{"content":"我喜欢 markdown 表格"}'

# 下次对话自动召回(无需显式调用)
你: 今天几只 ETF 表现
Agent: (自动从长期记忆召回偏好,输出 markdown 表格)
```

四类记忆:WORKING(当前交互) / EPISODIC(会话片段) / SEMANTIC(知识沉淀,向量检索) / PROCEDURAL(操作流程)。

---

### 任务6:危险操作需人机协同

**适用场景**:Agent 想 `rm -rf` / `git push --force` / 改生产配置。

```bash
# 设置策略:shell 类操作必须审批
curl -X POST http://localhost:8000/api/hitl/policy \
  -H "Content-Type: application/json" \
  -d '{"tool_pattern":"*shell*","action":"ASK"}'

# 之后 Agent 触发 shell 时:
你: 帮我删一下 /tmp/foo.log
Agent: [event: hitl_required]
→ 浏览器"审批中心"弹出 → 你点 [批准] 或 [拒绝]
```

策略:`PASS`(放行)/ `ASK`(每次问)/ `BLOCK`(禁止)。

---

### 任务7:多 Provider 调度

**适用场景**:OpenAI 抽风 / 你想根据成本动态选模型。

```python
agent.set_primary_standby(
    primary={"provider": "deepseek", "model": "deepseek-chat"},
    standbys=[
        {"provider": "qwen", "model": "qwen-turbo"},       # 国内兜底
        {"provider": "doubao", "model": "doubao-pro-32k"}, # 备用
    ],
    enable_warmup=True,
)
```

任何一层 Provider 失败,自动按 standbys 顺序切换。详见 README §3.3。

---

### 任务8:A/B 测试

**适用场景**:你想对比两版 Prompt / 两个模型的真实回答质量。

```python
from ab_testing import ABTest

test = ABTest(
    name="prompt-v2-vs-v1",
    variants={
        "v1": {"provider": "openai", "model": "gpt-4o-mini"},
        "v2": {"provider": "deepseek", "model": "deepseek-chat"},
    },
    metrics=["response_quality", "latency_ms"],
)
test.run(question="...", n=100)
print(test.report())
```

---

### 任务9:可观测

**适用场景**:你想看 Agent 内部到底发生了什么。

```bash
# 实时事件流
curl http://localhost:8000/api/events?limit=50 | jq .

# Trace 链路
curl http://localhost:8000/api/traces?limit=10 | jq .

# Prometheus 指标
curl http://localhost:8000/api/metrics/prometheus

# Grafana 接入:scrape http://<host>:8000/api/metrics/prometheus
```

支持的事件类型:`llm_call` / `tool_call` / `tool_result` / `memory_recall` / `hitl_decided` / `fallback` / `error` 等。

---

## 以下是按"功能维度"罗列的传统章节,用于查具体某个能力。

## 快速开始

### 启动方式

**方式一：Web 界面（推荐新手）**
```bash
cd e:\langChain_langGraph\ai_agent
python api.py
```
然后打开浏览器访问 `http://localhost:8000`

**方式二：命令行交互**
```bash
cd e:\langChain_langGraph\ai_agent
python main.py
```

**方式三：编程调用**
```python
from agent import AIAgent

agent = AIAgent()
agent.init_agent()  # 初始化

# 同步方式
result = agent.run("你好，请介绍一下自己")

# 流式方式
for chunk in agent.run_stream("你好"):
    print(chunk, end="")
```

---

## 功能一览

### 1️⃣ 智能问答

**直接对话，无需工具**：

| 示例 | 说明 |
|------|------|
| `你好` | 简单问候 |
| `什么是 ETF？` | 知识问答 |
| `帮我解释一下量子计算` | 概念解释 |

---

### 2️⃣ 文件操作

**文件读写、目录浏览**：

| 功能 | 示例 |
|------|------|
| 读文件 | `读取 README.md 文件` |
| 写文件 | `把这段文字写入 notes.txt` |
| 列目录 | `列出当前目录的文件` |

**限制**：
- 只能访问当前目录及子目录
- 禁止访问上级目录（`..`）
- 禁止绝对路径

---

### 3️⃣ 知识库问答

**基于本地文档回答问题**：

```bash
# 先加载文档到知识库
"请加载 knowledge_base 目录下的 python_intro.txt"

# 然后提问
"Python 中什么是装饰器？"
```

**支持的文档**：txt、md 等文本文件

---

### 4️⃣ ETF 金融分析

**基金信息、行情查询、对比分析**：

| 功能 | 示例 |
|------|------|
| 基本信息 | `查询 510300 ETF 的基本信息` |
| 实时行情 | `看看 510500 现在多少钱` |
| 历史数据 | `510300 近 30 天走势如何` |
| 知识学习 | `给我讲讲 ETF 的风险` |
| 对比分析 | `对比 510300 和 510500` |
| 综合分析 | `分析一下 159919 的走势` |

---

### 5️⃣ 代码执行

**安全的数学计算和表达式求值**：

| 示例 | 说明 |
|------|------|
| `计算 2^10 + sin(45度)` | 数学表达式 |
| `sqrt(144) * log(100)` | 嵌套函数 |
| `e^3 / pi` | 常量计算 |

**安全限制**：
- 禁止 `import`、`exec`、`eval`
- 禁止文件/网络操作
- 仅支持数学和安全函数

---

### 6️⃣ 实用工具

| 功能 | 示例 |
|------|------|
| 天气查询 | `北京今天天气怎么样？` |
| 时间查询 | `现在几点了？` |
| 网络搜索 | `搜索一下 LangChain 最新资讯` |
| GitHub 搜索 | `帮我找找 Star 最多的 Python 项目` |
| 图表生成 | `生成一个销售数据的柱状图` |

---

### 7️⃣ 安全特性

**自动保护，无需干预**：

- **输入过滤**：拦截危险命令
- **输出脱敏**：隐藏敏感信息
- **意图识别**：理解用户真实需求

---

### 8️⃣ 中间状态可视化（v0.2.0+）

在对话时可以直接看到 Agent 的"思考过程"和"工具调用"，无需打开 DevTools。

- **工具调用时间线**：每条 AI 消息下方出现彩色 pill，告诉你"调了哪些工具"。
- **思考过程折叠面板**：如果模型在输出中写了 `## 思考 ##`，会自动折叠在前端（点开可看）。
- **安全拦截横幅**：输入被 `SecurityModule` 拒绝时，会出现 🛡️ 提示横幅，不会"静默失败"。

---

### 9️⃣ Prompt 版本管理（v0.2.0+）

设置面板 → Prompt 版本管理 → 可看到当前激活版本与历史版本：

- **v1.0.0**：与 v1.1.0 行为完全一致（兜底版）
- **v2.0.0**：默认启用 `## 思考 ## / ## 回答 ##` CoT 注入
- 一键回滚：点"回滚到此版"立即切换，下次会话生效

适用场景：模型效果回归 → 切回 v1.0.0；新版本验证 → 切到 v2.0.0。

---

## 使用技巧

### 🔥 技巧 1：连续对话

Agent 记得对话上下文，可以追问：

```
用户：查询 510300 的信息
助手：510300 ETF基本信息...
用户：再看看它的历史走势
助手：510300 近30天历史行情...
用户：那和 510500 比呢？
助手：【对比分析】...
```

### 🔥 技巧 2：组合任务

一个请求包含多个子任务：

```
"查询 510300 的最新价格，计算比昨天涨跌了多少，
 然后生成一个最近 30 天的走势图"
```

### 🔥 技巧 3：知识库问答

1. 先加载文档：
   ```
   "请加载 knowledge_base 目录下的所有文档"
   ```

2. 然后基于知识库提问：
   ```
   "文档中提到的 Python 最佳实践有哪些？"
   ```

---

## 常见问题

### ❓ 提示"API Key 未配置"

**解决方法**：
1. 在 Web 界面点击右上角 ⚙️ 设置
2. 输入你的 OpenAI API Key
3. 点击保存

或创建 `.env` 文件：
```env
OPENAI_API_KEY=sk-xxxxxxxxxxxx
```

### ❓ 文件操作失败

**常见原因**：
- 路径包含 `..`（上级目录）
- 使用了绝对路径（如 `C:\...`）
- 文件不存在

**解决方法**：使用相对路径，如 `README.md`、`./data/file.txt`

### ❓ 模型响应慢

**可能原因**：
- 网络延迟
- 复杂问题需要更多处理时间

**解决方法**：
- 等待一会再试
- 在 Web 界面设置中切换到更快的模型

### ❓ 回答不准确

**可能原因**：
- 知识库未加载相关文档
- 问题太模糊

**解决方法**：
- 先加载相关文档
- 问题更具体一些

---

## 配置选项

### 模型切换

在 Web 界面 ⚙️ 设置中可选择。v0.3.0 起支持 **11 个 provider / 70+ 个模型**，按 provider 分组展示：

| Provider | 说明 | 入口 |
|----------|------|------|
| **OpenAI** | GPT-4o / GPT-4 / o1 等 | 官方 |
| **DeepSeek** | 国产高性价比，含 R1 推理模型 | api.deepseek.com |
| **通义千问 (Qwen)** | 阿里云 DashScope；中文最强 | dashscope.aliyuncs.com |
| **智谱 GLM** | GLM-4 / GLM-Z1 推理 | open.bigmodel.cn |
| **Kimi (Moonshot)** | 超长上下文（128K） | api.moonshot.cn |
| **MiniMax** | MiniMax 01 / abab7 | api.minimax.chat |
| **文心一言 (Baidu)** | ERNIE 系列 | qianfan |
| **讯飞星火 (Spark)** | Spark 3.5 | 讯飞开放平台 |
| **豆包 (Doubao)** 🆕 | 字节跳动 / 火山方舟 ARK | ark.cn-beijing.volces.com |
| **腾讯混元 (Hunyuan)** 🆕 | Hunyuan 系列 | api.hunyuan.tencent.com |
| **硅基流动 (SiliconFlow)** 🆕 | 一站式接入 Qwen/DeepSeek/GLM 等 | api.siliconflow.cn |

> 💡 设置面板的下拉会按 provider 分组（蓝色标题）；未配置 API Key 的 provider 选项标灰禁用。
> 填入对应环境变量后，**刷新页面** 即可看到该项变为可选。

### 备选模型

当主模型不可用时，自动切换：

```python
agent.set_primary_standby(
    primary={"provider": "openai", "model": "gpt-4o-mini"},
    standbys=[
        {"provider": "deepseek", "model": "deepseek-chat"},
        {"provider": "qwen", "model": "qwen-turbo"},
        {"provider": "doubao", "model": "doubao-pro-32k"},   # 新增
    ]
)
```

### 配置国内模型 Key（.env 写法）

```env
# OpenAI
OPENAI_API_KEY=sk-...

# DeepSeek
DEEPSEEK_API_KEY=sk-...

# 通义千问（DashScope）
QWEN_API_KEY=sk-...

# 智谱 GLM
ZHIPU_API_KEY=...
# 或者
GLM_API_KEY=...

# Kimi（Moonshot）
MOONSHOT_API_KEY=sk-...

# 字节豆包（火山方舟 ARK）
DOUBAO_API_KEY=...

# 腾讯混元
HUNYUAN_API_KEY=...

# 硅基流动
SILICONFLOW_API_KEY=...

# 文心一言 / 讯飞星火（特殊协议，需另配）
BAIDU_API_KEY=...
BAIDU_SECRET_KEY=...
SPARK_APP_ID=...
SPARK_API_KEY=...
SPARK_SECRET_KEY=...
```

---

## 错误处理

### 自动容错

系统内置五层保护：

| 层级 | 保护机制 |
|------|----------|
| 1 | 请求超时重试 |
| 2 | 指数退避重试 |
| 3 | Provider 切换 |
| 4 | 熔断保护 |
| 5 | 降级回答 |

### 降级回答

当全部模型不可用时，会给出：

```
⚠️ 当前所有模型都不可用，已为您保存问题。

建议：
1. 等待片刻后重试
2. 在设置中切换其他模型
3. 检查网络连接
```

---

## 会话管理

### 查看历史

| 操作 | 方法 |
|------|------|
| 继续对话 | 在 Web 界面选择历史会话 |
| 清除历史 | `清除对话历史` |
| 新建会话 | Web 界面点击新建对话 |

### API 调用

```python
# 获取所有会话
sessions = agent.list_all_sessions()

# 切换会话
agent.set_session("session_id_here")

# 清除历史
result = agent.clear_history()
```

---

## API 参考

### 核心方法

```python
from agent import AIAgent

agent = AIAgent()

# 初始化
agent.init_agent(provider="openai", model_name="gpt-4o-mini")

# 同步对话
result = agent.run("你好")

# 流式对话
for chunk in agent.run_stream("你好"):
    print(chunk, end="")

# 获取状态
status = agent.get_api_key_status()
print(f"Provider: {status['provider']}")
print(f"Model: {status['model']}")

# 获取工具列表
tools = agent.get_tools_list()
print(f"可用工具: {', '.join(tools)}")
```

---

## 技术支持

- GitHub Issues: https://github.com/colbertlee/langChain_langGraph/issues
- 文档更新: 查看 [README.md](README.md)
- 详细变更: 查看 [CHANGELOG.md](../CHANGELOG.md)
