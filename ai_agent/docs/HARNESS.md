# Harness(Agent 通用运行时门面)

`ai_agent/harness.py` 提供 **薄包装门面**,把现有 `tools / memory / permission / planner / sandbox / observability / security` 串成一根线,对外只暴露 `Harness.run() / run_stream()` 一个概念。

设计原则:**不替换、不重写** 任何现有模块,只做编排。Harness 是入口,不是实现。

---

## 五件套对应

| Harness 职责 | 现有模块 | Harness 接入点 |
|---|---|---|
| 1. 工具桥接 | `tools.py` + `mcp_tools.py` | `agent.run()` 内部(不接管) |
| 2. Agent 主循环 | `agent.py: AIAgent.run()` | Harness.run → agent.run |
| 3. 上下文与记忆 | `context_manager.py` + `memory_store.py` | 前置/后置打点 |
| 4. 安全与权限护栏 | `security.py` + `permission.py` + `sandbox.py` | 前置检查,trace 打点 |
| 5. 调度编排 | `planner.py` + `multi_agent.py` | 前置 plan,trace 打点 |

---

## 使用

```python
from harness import Harness, HarnessConfig

cfg = HarnessConfig(
    session_id="user-42",          # 为 None 时自动生成
    sandbox="standard",            # off / standard / strict
    enable_planner=False,          # 默认 False(planner 不强制开启)
    enable_memory=True,            # 默认 True(写 memory_store)
    enable_observability=True,     # 默认 True(写 observability)
    enable_security=True,          # 默认 True
    extra_tags={"tenant": "demo"}, # 透传到 observability 指标
)
h = Harness.from_config(cfg)

# 同步
reply = h.run("你好")
print(reply)

# 流式
for chunk in h.run_stream("解释这段代码"):
    print(chunk, end="")

# 拿到本次完整轨迹
trace = h.last_trace
trace.to_dict()  # → 可写盘/贴 PR
```

### 注入自定义子模块(用于单测 / 多租户)

```python
from harness import Harness

h = Harness(
    agent=my_agent,
    security=my_security,
    permission=my_guard,
    memory_store=my_memory,
    observability=my_obs,
)
```

显式传 `None` 表示 "强制关闭该子系统"(不 lazy load)。

---

## Trace 数据结构

```python
@dataclass
class TraceStep:
    stage: str               # security / planner / memory / observability / agent
    name: str                # 步骤短名
    started_at: float        # monotonic 秒
    duration_ms: float
    status: str              # ok / fail / skip
    detail: Dict[str, Any]   # 子模块自定义元数据

@dataclass
class Trace:
    session_id: str
    prompt: str
    started_at: str          # ISO8601
    finished_at: str
    output: str
    error: Optional[str]
    steps: List[TraceStep]
```

---

## 防御性降级

- 任一子系统抛异常 → 只在对应 `step.status = "fail"` 打点,不中断主流程
- 任一子系统不可用 → 直接跳过对应 step(`status = "ok"` 但不出现在 trace 里)
- agent 抛异常 → 返回 `"❌ Harness error: ..."`,同时 `trace.error` 记录

---

## 与 Eval Harness 协作

Eval Harness (`harness_runner.py` / `harness_storage.py` / `harness_cli.py`) 是评测外框,与本 Harness(运行时门面)是两套独立模块:

| 模块 | 角色 |
|---|---|
| `harness.py` | **Agent 运行时门面**(本文件) |
| `harness_runner.py` / `harness_storage.py` / `harness_cli.py` | **Eval Harness**(CI 评测) |

可串起来用——Eval Harness 跑用例时把 AIAgent 换成 Harness:

```python
from harness import Harness
from harness_runner import HarnessRunner, HarnessCase
from harness_storage import Storage

h = Harness.from_config(HarnessConfig(enable_observability=True))
agent_wrapper = type("A", (), {"run": lambda self, prompt, session_id=None: h.run(prompt)})()
runner = HarnessRunner(agent=agent_wrapper)
result = runner.run([HarnessCase(id="t", prompt="hi", expected="hi")])
Storage.write(result)
```

---

## 测试

```bash
pytest tests/test_harness_facade.py -v --no-cov
```

25 个用例,纯 fake agent,不调真实 LLM,可离线运行。