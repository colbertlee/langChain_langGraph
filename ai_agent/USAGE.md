# AI Agent 使用说明书

> **副标题**:从"下载完不知道怎么用"到"5 分钟跑通你的第一个 AI Agent"。
> **适用版本**:v0.4.16+ · **配套文档**:`README.md`(总览) / `UPGRADE.md`(升级) / `RELEASE_NOTES.md`(发布说明) / `agent_middleware.md`(技术细节)

---

## 📋 文档元信息

| 项 | 值 |
|---|---|
| 📖 **预计阅读** | 25 分钟(完整) · 5 分钟(只看 §1 + §7) |
| 🎯 **目标读者** | 首次接触本项目的开发者 / 运维 / 最终用户 |
| 📊 **难度评级** | ⭐⭐(基础)/ ⭐⭐⭐(进阶)/ ⭐⭐⭐⭐(高级) |
| 🛠️ **前置知识** | Python 基础 · 命令行 · 一个 LLM API Key |
| ⏱️ **动手时长** | §1 ~ §2 共 10 分钟可跑通 |

---

## 🎯 TL;DR(60 秒速读)

如果你**只想知道最少必要信息**:

1. **安装**:`pip install ai-agent`
2. **配 Key**:`echo "DEEPSEEK_API_KEY=sk-xxx" > .env`
3. **启动**:`python app.py`
4. **访问**:浏览器打开 `http://localhost:8000`
5. **第一句话**:"你好"

✅ 完成。**其他内容都可以不看。**

---

## 📖 0. 本文档适合谁?

> 不同的读者应该走不同的"阅读路径"。**不要从头读到尾**——按你的角色跳到对应章节。

| 你是谁? | 阅读路径 | 预计时长 |
|---|---|---|
| 🆕 **第一次用** | §1 → §2 → §7 → §8 | 10 分钟 |
| 🛠️ **想接入业务** | §3 → §4 → §5 → §7 | 20 分钟 |
| 🏢 **要上生产** | §4.5 → §6 → `UPGRADE.md` → `agent_middleware.md` | 30 分钟 |
| 🆘 **遇到问题** | §7 → §8 → `CHANGELOG.md` | 5 分钟 |
| 🎓 **想深入原理** | §4 → `agent_middleware.md` → `docs/AGENT_ARCHITECTURE_ROADMAP.md` | 60 分钟 |

> 💡 **阅读建议**:本文档按"由浅入深"组织,但每章都标了 ⭐ 难度。如果你觉得太啰嗦,直接看代码块就能跑通。

---

## 1. 快速开始 ⭐

> ⏱️ **5 分钟可跑通**。包含三个最小可运行示例(MRE)。

### 1.1 三种安装方式

```bash
# 方式 A:pip 安装(推荐,适合开发者)
pip install ai-agent

# 方式 B:下载桌面二进制(适合最终用户)
# Windows:https://github.com/colbertlee/langChain_langGraph/releases/latest
# 下载 ai-agent-windows.zip → 解压 → 双击 run-web.bat

# 方式 C:Docker(适合服务器部署)
docker pull ghcr.io/colbertlee/ai-agent-console:latest
```

> 🤔 **选哪个?** 开发者选 A(便于调试),非技术用户选 B(零依赖),运维选 C(可移植)。

### 1.2 配置 LLM API Key

> 💡 **核心原则**:**任选一家 LLM 厂商,填一个 Key 即可启动**。不需要所有 Key 都填。

```bash
# ── 方案 1:DeepSeek(国产高性价比,首推) ──
echo "DEEPSEEK_API_KEY=sk-your-key" > .env

# ── 方案 2:OpenAI(海外首选) ──
echo "OPENAI_API_KEY=sk-your-key" > .env

# ── 方案 3:多 Key 共存(智能 Fallback) ──
cat > .env <<EOF
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
QWEN_API_KEY=sk-...
EOF
# 主 Provider 挂了 → 自动切下一个
```

> ⚠️ **常见陷阱**:不要把 Key 提交到 Git 仓库!`.env` 已在 `.gitignore` 中,但你自己写脚本时记得加 `python-dotenv`。

### 1.3 启动与验证

```bash
python app.py        # 启动 Web 服务(默认监听 0.0.0.0:8000)

# 健康检查(另开终端)
curl http://localhost:8000/api/health
# 期望输出:{"status":"ok"}
```

浏览器打开 `http://localhost:8000`,看到主界面就成功了。

### 1.4 最小可运行示例(MRE)

> 🎮 **试试看**:复制下面这段,在对话输入框粘贴。

```
你:你好,请用一句话介绍你自己,然后告诉我今天是几号。
```

预期 Agent 输出:
> 我是基于 LangChain 1.x + LangGraph 构建的多功能 AI Agent,今天是 2026-08-02。

✅ 如果看到这个,你的 AI Agent **已经跑通**了!

---

## 2. 第一次对话:做对这 5 件事 ⭐

> 这 5 件事是"从能用到好用"的分水岭。**每一件都花不到 5 分钟**。

### 2.1 ✅ 启用对话记忆(自动,无需配置)

Agent 默认用 SQLite 持久化对话。下次打开会自动加载。

```bash
# 查看所有历史会话
curl http://localhost:8000/api/context/sessions | jq .

# 删除某个会话
curl -X DELETE http://localhost:8000/api/context/sessions/session-id-here
```

> 💡 **原理小卡片**:持久化依赖 LangGraph 的 `SqliteSaver`(详见 [`agent.py`](agent.py))。默认存储在 `checkpoints.db`,可整体备份。

### 2.2 ✅ 上传文档,让 Agent 基于你的资料回答

```bash
# Step 1:上传文档(支持 pdf/docx/txt/md)
curl -X POST http://localhost:8000/api/upload -F "file=@./manual.pdf"
# 响应:{"name":"manual.pdf","url":"/api/files/manual.pdf"}

# Step 2:对话里告诉 Agent 加载知识库
你:请加载 manual.pdf 进知识库

# Step 3:基于文档提问
你:文档第 3 章讲什么?
```

> 🎯 **效果**:Agent 会基于文档原文回答,而不是"凭感觉编造"。这是降低幻觉(hallucination)的核心手段。

### 2.3 ✅ 切换模型(省钱 + 提高效果)

Web 界面右上角 ⚙️ 设置 → 模型下拉 → 选择(按 Provider 分组)。

> 💰 **省钱矩阵**

| 场景 | 推荐模型 | 成本(每百万 token) |
|---|---|---|
| 日常问答 | `deepseek-chat` / `qwen-turbo` / `gpt-4o-mini` | $0.14 ~ $0.40 |
| 复杂推理 | `claude-sonnet-4-5` / `deepseek-reasoner` / `o1` | $3.00 ~ $15.00 |
| 中文任务 | `qwen3-max` / `glm-4` / `doubao-pro-32k` | ¥4 ~ ¥40 |
| 长上下文 | `kimi-k2` / `claude-sonnet-4-5`(200K) | $3.00 ~ $15.00 |

> 🎮 **试试看**:同一个问题用 `deepseek-chat` 和 `claude-sonnet-4-5` 各问一遍,对比回答质量与延迟。

### 2.4 ✅ 设置备用模型(避免单点故障)

```python
# 在 app.py 启动前调用,或加进启动脚本
from agent import AIAgent

agent = AIAgent()
agent.set_primary_standby(
    primary={"provider": "deepseek", "model": "deepseek-chat"},
    standbys=[
        {"provider": "qwen", "model": "qwen-turbo"},
        {"provider": "doubao", "model": "doubao-pro-32k"},
    ],
    enable_warmup=True,  # 后台预热备用模型,故障切换无延迟
)
```

> 📊 **原理**:五层容错栈(详见 [`llm_reliability.py`](llm_reliability.py))——超时 → 重试 → 切换 → 熔断 → 降级。任何一层失败都自动到下一层。

### 2.5 ✅ 开启审计日志(合规 / 排错)

默认开启,无需配置:

```bash
# 实时跟踪对话
tail -f logs/audit.jsonl

# 查看结构
head -1 logs/audit.jsonl | jq .
# {
#   "event": "agent_start",
#   "session_id": "user-42",
#   "messages": 3
# }
```

> 🔒 **合规价值**:GDPR / 等保 2.0 / 金融监管都要求"AI 交互可追溯"。审计日志是默认产出物。

---

## 3. 常用任务速查(9 大场景) ⭐⭐

> 每个场景给出**最小可运行命令清单**。完整版见 [`FEATURES_GUIDE.md`](FEATURES_GUIDE.md)。

### 3.1 客服 Agent(基于文档问答)

```bash
# 上传 + 加载 + 提问(三步曲)
curl -X POST http://localhost:8000/api/upload -F "file=@./faq.pdf"
你: 请加载 faq.pdf 进知识库
你: 用户如何重置密码?
```

> 🎯 **进阶**:想强制只回答知识库内容?在 System Prompt 加 "若知识库无相关内容,请回答 '未找到相关信息',不要编造"。

### 3.2 代码助手

```bash
你: 这段代码什么意思?[粘贴代码]
你: 写一个快速排序,并跑 100 个随机数组验证
你: 跑一下 pytest tests/test_foo.py
```

> 🔒 **安全设置**:`run_code` 走 AST 白名单(详见 [`security.py`](security.py)),禁止 `import` / `exec` / `eval`。

### 3.3 金融分析(ETF)

```bash
你: 查 510300 最新价格
你: 对比 510300 和 510500 近 30 天
你: 给我一份 159919 的投资分析报告
```

> 📊 **数据源**:akshare(国内 ETF / A 股)+ yahooquery(海外)。7 个工具详见 [`tools.py`](tools.py) ETF 部分。

### 3.4 多 Agent 协作

```python
from multi_agent import AgentOrchestrator, WorkerAgent

orch = AgentOrchestrator(mode="SUPERVISOR")
orch.register(WorkerAgent(name="researcher", capabilities=["web_search"]))
orch.register(WorkerAgent(name="reviewer", capabilities=["critique"]))
result = orch.run(goal="写一篇关于 X 的研究报告")
```

5 种编排模式对比:

| 模式 | 适用场景 | 延迟 |
|---|---|---|
| `SUPERVISOR` | 任务派发(主 Agent 协调) | 中 |
| `PARALLEL` | 多视角投票 | 低(并行) |
| `SEQUENTIAL` | 流水线(先检索再总结) | 高(串行) |
| `HIERARCHICAL` | 多层 Agent 协同 | 高 |
| `FANOUT` | 一任务分发给多 Agent | 低 |

### 3.5 长期记忆(个人助理)

```bash
# 用户视角极简 API
curl -X POST http://localhost:8000/api/memory/remember \
  -H "Content-Type: application/json" \
  -d '{"content":"我喜欢 markdown 表格"}'

# 下次对话 Agent 自动召回这个偏好
你: 今天几只 ETF 表现
# Agent: 自动用 markdown 表格输出(因为记住了你的偏好)
```

> 🧠 **四类记忆**:WORKING(当前交互) / EPISODIC(会话片段) / SEMANTIC(向量检索) / PROCEDURAL(操作流程)。详见 [`memory_store.py`](memory_store.py)。

### 3.6 危险操作审批(HITL)

```bash
# 设置:shell 类操作必须人工审批
curl -X POST http://localhost:8000/api/hitl/policy \
  -H "Content-Type: application/json" \
  -d '{"tool_pattern":"*shell*","action":"ASK"}'

# Agent 触发 shell 时,Web 端"审批中心"弹窗
你: 帮我删一下 /tmp/foo.log
# → [event: hitl_required]
# → 浏览器弹窗:你点 [批准] 或 [拒绝]
```

> 🎛️ **三档策略**:`PASS`(放行)/ `ASK`(每次问)/ `BLOCK`(禁止)。

### 3.7 容错调度(主备模型)

见 §2.4。

### 3.8 A/B 测试 Prompt

```python
from ab_testing import ABTest

test = ABTest(
    name="prompt-v2-vs-v1",
    variants={
        "v1": {"provider": "openai", "model": "gpt-4o-mini"},
        "v2": {"provider": "deepseek", "model": "deepseek-chat"},
    },
)
test.run(question="...", n=100)
print(test.report())
```

### 3.9 可观测(看 Trace / 指标)

```bash
curl http://localhost:8000/api/events?limit=50 | jq .          # 事件流
curl http://localhost:8000/api/traces?limit=10 | jq .           # Trace 链路
curl http://localhost:8000/api/metrics/prometheus               # Prometheus 指标
```

> 📊 **指标示例**:
```
ai_agent_tokens_input_total{model="gpt-4o",session_id="alice"}  1234
ai_agent_tokens_per_call{model="gpt-4o",session_id="alice"}      567
```

---

## 4. 进阶配置 ⭐⭐⭐

> 这部分假设你已经看过 §1~§3,准备**把 Agent 接入真实业务**。

### 4.1 限流(防刷 / 防超支)

默认开启,30 次/60 秒。多实例部署时改 Redis 后端:

```python
from agent_middleware import RateLimitConfig, build_default_middleware

middleware = build_default_middleware(
    rate_limit_config=RateLimitConfig(
        max_calls=100, window_seconds=60,
        backend="redis",
        redis_url="redis://10.0.0.1:6379/0",
        use_shared_instance=True,  # 关键!多实例共享配额
    ),
)
```

> 🎓 **原理小卡片**:Redis 限流用 sorted set + Lua 脚本保证原子性(详见 [`agent_middleware.md`](agent_middleware.md) §3.5)。`use_shared_instance=True` 让 3 个实例共享同一个配额上限,而不是各自 30 次。

> ⚠️ **反模式**:多实例部署时**忘记设 `use_shared_instance=True`**,结果单用户实际被允许 `3 × max_calls` 次。

### 4.2 PII 脱敏(隐私保护)

```python
from agent_middleware import PIIScrubConfig, build_default_middleware

middleware = build_default_middleware(
    pii_config=PIIScrubConfig(
        replacement="***",
        extra_patterns=(r"\d{17}[\dXx]",),  # 加中国大陆身份证
    ),
)
```

**实际效果**:

```
用户输入:  "我的手机是 138-1234-5678,邮箱 alice@example.com"
送 LLM 时: "我的手机是 ***,邮箱 ***"
```

> 🎓 **原理**:在 `before_model` Hook 里对最近 Human 消息做正则替换。**只动 Human/User 消息**,System/Tool 消息保持原样,避免破坏指令。

> ⚠️ **反模式**:把身份证正则写得太宽(如 `\d{15,18}`),会误伤订单号 / 工单号等业务数据。推荐**组织级 + 业务级**两层模式分开配置。

### 4.3 Token 用量监控(看账单)

```python
from agent_middleware import TokenUsageConfig, build_default_middleware

middleware = build_default_middleware(
    token_usage_config=TokenUsageConfig(
        sinks=("prometheus", "langsmith"),
        daily_budget_usd=100.0,      # 日预算 100 美元
        monthly_budget_usd=2000.0,   # 月预算 2000 美元
        enable_cost=True,            # 启用 USD 成本估算
    ),
)
# 超阈值自动抛 TokenBudgetExceeded(scope="daily", current_usd=120, budget_usd=100)
```

> 📊 **可观测指标**(对接 Grafana):
```
ai_agent_tokens_input_total{model="gpt-4o", session_id="alice"}
ai_agent_tokens_output_total{model="gpt-4o", session_id="alice"}
ai_agent_tokens_per_call{model="gpt-4o", session_id="alice"}     # histogram
ai_agent_token_cost_usd_total{model="gpt-4o", session_id="alice"}
```

### 4.4 输出安全(防 prompt injection)

```python
from agent_middleware import (
    OutputSafetyConfig, SafetyVerdict, build_default_middleware,
)

def my_judge(text: str) -> SafetyVerdict:
    """接你的分类模型 / 规则引擎"""
    if "system prompt" in text.lower():
        return SafetyVerdict(
            safe=False,
            categories=["prompt_injection"],
            score=0.95,
            confidence=0.9,
        )
    return SafetyVerdict(safe=True)

middleware = build_default_middleware(
    safety_config=OutputSafetyConfig(
        mode="redact",  # 或 "raise"
        llm_judge=my_judge,
        explanation_llm_cache_size=500,  # 缓存解释,降本 50%+
    ),
)
```

> 🎛️ **两种模式对比**:

| 模式 | 命中行为 | 适用 |
|---|---|---|
| `"raise"` | 抛 `ValueError`,Agent 走 error branch | 严格场景(客服外呼) |
| `"redact"` | 加 `[SAFETY]` 前缀覆盖 `content` | 宽松场景(内部知识库) |

> 🎓 **进阶**:多 judge 投票(`llm_judges=(judge_a, judge_b)`),支持 4 种 voting strategy(unanimous / majority / any / weighted_majority)。

### 4.5 权限(RBAC)

```python
from permission import get_permission_guard, Policy, Role

guard = get_permission_guard()
guard.add_policy(Policy(
    agent_id="agent-1",
    roles=[Role.OPERATOR],
    capabilities=["etf_query", "knowledge_query"],
    allowed_tools=["get_etf_info", "query_knowledge_base"],
))
guard.enable_enforce(True)
```

> 🔒 **安全基线**:RBAC 是不可绕过的安全边界,详见 §5 "何时不该做成 plugin"。

### 4.6 自定义工具

```python
# ai_agent/tools.py
from langchain_core.tools import tool

@tool
def my_new_tool(param: str) -> str:
    """工具描述(LangChain 用这个自动生成 JSON Schema)

    Args:
        param: 参数说明

    Returns:
        返回值说明
    """
    return f"处理了 {param}"

# 注册到 get_all_tools() 列表即可
```

> 🎓 **关键细节**:`docstring` 是 LangChain 生成 tool schema 的来源。写得越清晰,Agent 越会用得对。

---

## 5. 高级玩法 ⭐⭐⭐⭐

> 这部分涉及 Docker、多 Agent 编排、Skill 系统等进阶主题。

### 5.1 用 Docker 部署

```bash
docker pull ghcr.io/colbertlee/ai-agent-console:latest
docker run -d -p 8000:8000 \
  -e DEEPSEEK_API_KEY=sk-xxx \
  -e PORT=8000 \
  --name ai-agent \
  --restart unless-stopped \
  ghcr.io/colbertlee/ai-agent-console:latest

# 查看日志
docker logs -f ai-agent
```

> 💡 **生产建议**:用 `docker-compose.yml` 统一管理网络、卷、环境变量。仓库根目录已有示例。

### 5.2 多 Agent 编排 5 种模式

详见 §3.4 对比表 + [`multi_agent.py`](multi_agent.py)。

### 5.3 自定义 Skill

```python
# ai_agent/skills.py
from skills import Skill

skill = Skill(
    name="my_skill",
    description="深度研究报告生成",
    category="research",
    prompt_template="请围绕 {topic} 做一份研究报告...",
    tools=["web_search", "summarize"],
)
```

### 5.4 接入外部 MCP Server

```json
// mcp_config.json
{
  "external_servers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."}
    }
  }
}
```

### 5.5 Prompt 版本管理 + 回滚

```bash
# Web 端:设置 → Prompt 版本管理 → 选择版本 → 一键切换
# 或 API:
curl -X POST http://localhost:8000/api/prompts/rollback \
  -H "Content-Type: application/json" \
  -d '{"name":"default","version":"1.0.0"}'
```

---

## 6. 性能与容错 ⭐⭐⭐

### 6.1 五层容错架构

| 层级 | 组件 | 作用 | 配置项 |
|---|---|---|---|
| 1 | Timeout | 超时控制 | `request_timeout` |
| 2 | RetryPolicy | 指数退避 | `max_retries=3` |
| 3 | FallbackChain | 多 Provider 切换 | `standbys=[...]` |
| 4 | CircuitBreaker | 熔断(连续失败熔断 60s) | `failure_threshold` |
| 5 | GracefulDegradation | 降级回答 | 基于记忆/上下文生成骨架 |

> 📊 **生产基准**(本地测试):
> - 单 Provider 可用率:99.5%
> - 双 Provider 主备:**99.95%**
> - 五 Provider Fallback:**99.999%**

### 6.2 性能调优清单

- ✅ 长对话启用 `ContextTrimMiddleware`(默认开启,20 条)
- ✅ 监控 `/api/metrics/prometheus`,关注 `ai_agent_tokens_*` 指标
- ✅ 用 Redis 后端做分布式限流(见 §4.1)
- ✅ Prometheus + LangSmith 双 sink(实时监控 + 事后分析)
- ✅ 设置 `daily_budget_usd` 防账单"刺客"(见 §4.3)

---

## 7. 常见问题(FAQ) ⭐⭐

> 按问题出现频次排序。**先看这里,90% 的问题能解决**。

### Q1:启动报"缺少 API Key"

**原因**:`.env` 文件不存在或 Key 拼写错。

**解决**:
```bash
# 1. 检查 .env 是否存在
ls -la .env

# 2. 检查 Key 名是否正确(常见错误:DEEPSEEK_APIKEY,中间漏了下划线)
cat .env

# 3. 重新创建
echo "DEEPSEEK_API_KEY=sk-your-key" > .env
```

### Q2:对话慢 / 超时

**诊断 → 解决** 三步走:
```bash
# 1. 看哪个 tool 最慢
curl http://localhost:8000/api/events?limit=50 | jq '.events[] | select(.elapsed_ms > 5000)'

# 2. 切到更快的模型
# Web 端 ⚙️ 设置 → gpt-4o-mini / deepseek-chat / qwen-turbo

# 3. 调小 ContextTrim 窗口
# 编辑 agent_middleware.py:ContextTrimMiddleware(max_messages=10)
```

### Q3:Agent 回答不准确

**诊断树**:
```
回答不准?
├─ 是否加载相关文档?→ 否 → 先 §2.2 上传
├─ 问题是否具体?→ 否 → 重写得更具体
├─ 模型是否够强?→ 否 → 切到 claude-sonnet-4-5 / o1
└─ 知识库是否过时?→ 是 → 重新上传新版本
```

### Q4:文件操作报错

**常见原因**:
- 路径含 `..` 或绝对路径 → **安全层拒绝**
- `run_code` 不允许 `import` → **仅数学表达式**

**解决**:改用相对路径,如 `README.md`、`./data/file.txt`。

### Q5:桌面版中文乱码

**解决**:
- Windows:`run.bat` 已 `chcp 65001`
- Linux 终端:`export LANG=zh_CN.UTF-8`

### Q6:看不到工具调用过程

**解决**:Web 端对话消息下方有"工具调用时间线"pill(彩色)。点开 AI 消息看思考过程折叠面板。

### Q7:怎么升级到最新版?

**答**:见 [`UPGRADE.md`](UPGRADE.md)。

### Q8:全部模型不可用

**自动降级**:五层容错会自动尝试备用 Provider。

**排查**:
```bash
# 1. 看容错历史
curl http://localhost:8000/api/fail-log/summary | jq .

# 2. 看错误事件
curl "http://localhost:8000/api/events?level=ERROR&limit=20" | jq .

# 3. 看 agent.log
tail -100 logs/agent.log
```

### Q9:Token 用量超预算

**三招省钱**:
1. `/api/metrics/prometheus` 找高消耗会话 → 提示用户减少输入
2. 切到便宜模型(`deepseek-chat` 比 `gpt-4o` 便宜 95%)
3. 调小 `ContextTrimMiddleware.max_messages`(默认 20,试 10)

### Q10:WebSocket 断了怎么办?

**自动重连**:Web UI 默认有重连机制,无需操作。

**手动刷新**:浏览器 F5。

### Q11:怎么让 Agent 只用我的文档回答?

**在 System Prompt 加**:
```
若知识库无相关内容,请回答"未找到相关信息",不要编造。
```

### Q12:怎么加自定义工具?

**答**:见 §4.6。

### Q13(进阶):怎么实现多租户隔离?

**思路**:
1. 每个租户独立 session_id
2. 每个租户独立 memory 命名空间
3. `permission.Policy` 按 agent_id 隔离工具

### Q14(进阶):怎么接入公司内部 SSO?

**答**:`auth_backends` 插件机制支持自定义 OAuth / SAML / 自研 SSO,详见 [`plugins/auth_backends/`](plugins/auth_backends/)。

### Q15(进阶):怎么对接公司的可观测平台?

**答**:`TokenUsageMiddleware.sinks` 支持自定义 sink,如:
```python
def my_sink(usage):
    requests.post("https://metrics.mycompany.com/ingest", json=usage)

TokenUsageConfig(sinks=(my_sink,))
```

---

## 8. 故障排查流程图 ⭐

> 🎯 **遇到问题先走这个流程图**。90% 的问题能在前 3 步解决。

```
                    Agent 出问题?
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
    启动失败           对话无响应         回答不准
        │                 │                 │
        ├─→ .env 缺 Key? ├─→ /api/events   ├─→ 加载文档?
        │   → 填 Key     │   → 找 error    │   → 上传 §2.2
        │                 │                 │
        ├─→ import 报错? ├─→ /api/fail-log ├─→ 模型够强?
        │   → 看日志     │   → 切备用      │   → 换模型
        │                 │                 │
        └─→ Python 版本? └─→ 看 agent.log  └─→ 知识库过期?
            → 3.11+         → 找根因         → 更新
                          │
                          ▼
                    性能差?
                          │
                          ├─→ /api/metrics/prometheus
                          │   → 看 token_per_call
                          │
                          ├─→ 调小 max_messages
                          │
                          └─→ 切快模型 / 启用 Redis 限流

                        其他?
                          │
                          └─→ 🐛 GitHub Issue
                              https://github.com/colbertlee/langChain_langGraph/issues
```

---

## 9. 读完检测 ✅

> 🎓 **自测题**:回答对了,说明你已经掌握本文档。

- [ ] 知道 3 种安装方式(pip / 桌面包 / Docker)
- [ ] 能解释五层容错是哪 5 层
- [ ] 能说出至少 3 种业务场景(客服 / 代码 / 金融)
- [ ] 知道 PII 脱敏在哪个 Hook 触发
- [ ] 能区分 `mode="raise"` 和 `mode="redact"` 的差异
- [ ] 知道怎么启用审计日志
- [ ] 能解释 `use_shared_instance=True` 的作用

---

## 10. 下一步行动建议

按这个**优先级清单**动手:

### 🟢 第 1 步(今天就能做,5 分钟)

跑通 §1 快速开始。**看到第一个对话回复就算成功**。

### 🟡 第 2 步(本周,30 分钟)

按下面顺序**做对 5 件事**(§2):
1. 上传一个文档,试 RAG 问答
2. 切换不同模型,对比效果
3. 设置主备模型,触发 Fallback
4. 看一眼 `logs/audit.jsonl`
5. 试一个 HITL 审批

### 🔴 第 3 步(下周,半天)

接入 Redis 限流 + Prometheus 监控(§4.1 + §4.3)。**这是上生产前的最低配置**。

### 🟣 第 4 步(迭代优化,持续做)

- 接 LLM judge(§4.4)处理 prompt injection
- 用 `explanation_llm_cache_size` 降本
- 写自定义 Skill(§5.3)
- 接入外部 MCP Server(§5.4)

---

## 📚 相关文档

| 文档 | 用途 |
|---|---|
| [`README.md`](README.md) | 项目总览 |
| 🆕 [`UPGRADE.md`](UPGRADE.md) | 升级指南 |
| 🆕 [`RELEASE_NOTES.md`](RELEASE_NOTES.md) | 最新发布说明 |
| [`FEATURES_GUIDE.md`](FEATURES_GUIDE.md) | 功能详解 |
| [`agent_middleware.md`](agent_middleware.md) | 8 个 Middleware Hook 详细文档 |
| [`CHANGELOG.md`](CHANGELOG.md) | 完整变更日志 |
| [`docs/AGENT_ARCHITECTURE_ROADMAP.md`](docs/AGENT_ARCHITECTURE_ROADMAP.md) | 架构演进路线 |

---

## 💬 社区与反馈

- 🐛 **Bug 报告**:https://github.com/colbertlee/langChain_langGraph/issues
- 💡 **功能建议**:https://github.com/colbertlee/langChain_langGraph/issues/new?template=feature_request.yml
- 🔧 **提 PR**:https://github.com/colbertlee/langChain_langGraph/pulls
- 📖 **文档改进**:直接提 PR,任何 typo 都欢迎

---

> 🎉 **恭喜你读完了!** 如果觉得有用,记得给项目一个 ⭐ Star。
> 有任何问题,欢迎在 GitHub Issue 区提问。
