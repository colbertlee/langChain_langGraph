"""
Agent 通用运行时 Harness(薄包装门面)。

目标:
- 把现有 tools / memory / permission / planner / sandbox / observability 串成一根线
- 对外只暴露 Harness.run() / run_stream() 一个概念
- 不替换/不重写任何现有模块,仅做编排
- 防御性降级:任何子模块缺失/失败都不抛未捕获异常

设计原则(与 agent.py 一致):
1. 防御性降级
2. 单一真相源(配置来自 HarnessConfig dataclass)
3. 职责分离(本类只编排,不实现工具/记忆/护栏逻辑)
4. 可观测:每次 run 自动产出 Trace,写到 observability + 暴露为 last_trace

使用:
    from harness import Harness, HarnessConfig
    h = Harness()  # 默认:从环境变量/单例工厂拼装
    reply = h.run("你好")
    for chunk in h.run_stream("解释这段代码"):
        print(chunk, end="")
    h.last_trace.to_dict()  # → 写盘/贴 PR
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 配置
# ============================================================

@dataclass
class HarnessConfig:
    """Harness 行为开关。所有字段都有合理默认值。"""
    session_id: Optional[str] = None              # 为 None 时由 Harness 自动生成
    sandbox: str = "off"                          # off / standard / strict
    enable_planner: bool = False
    enable_memory: bool = True
    enable_observability: bool = True
    enable_security: bool = True
    extra_tags: Dict[str, str] = field(default_factory=dict)
    # 透传给 AIAgent.run() 的额外参数
    agent_kwargs: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 轨迹(用于回放/调试/上报)
# ============================================================

@dataclass
class TraceStep:
    """Harness 编排链路上的一个事件"""
    stage: str                                    # security / permission / sandbox / planner / context / memory / agent / observability
    name: str                                     # 步骤短名,如 "intent_check"
    started_at: float                             # monotonic 秒
    duration_ms: float = 0.0
    status: str = "ok"                            # ok / skip / fail
    detail: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Trace:
    """一次 Harness.run() 的完整轨迹"""
    session_id: str
    prompt: str
    started_at: str                               # ISO8601
    finished_at: str = ""
    steps: List[TraceStep] = field(default_factory=list)
    output: str = ""
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "prompt": self.prompt,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "output": self.output,
            "error": self.error,
            "steps": [
                {
                    "stage": s.stage,
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 3),
                    "status": s.status,
                    "detail": s.detail,
                }
                for s in self.steps
            ],
        }


# ============================================================
# 内部工具:每个子系统的"可选"加载
# ============================================================

def _try_load_security():
    try:
        from security import get_security_instance
        return get_security_instance()
    except Exception as e:  # noqa: BLE001
        logger.debug("[harness] security unavailable: %s", e)
        return None


def _try_load_permission():
    try:
        from permission import get_permission_guard
        return get_permission_guard()
    except Exception as e:  # noqa: BLE001
        logger.debug("[harness] permission unavailable: %s", e)
        return None


def _try_load_sandbox(level: str):
    if level == "off":
        return None
    try:
        from sandbox import SandboxLevel, SandboxPolicy, get_sandbox_runner
        enum = SandboxLevel.STANDARD if level == "standard" else SandboxLevel.STRICT
        policy = SandboxPolicy(level=enum)
        return get_sandbox_runner(policy)
    except Exception as e:  # noqa: BLE001
        logger.debug("[harness] sandbox unavailable: %s", e)
        return None


def _try_load_context():
    try:
        from context_manager import get_context_manager
        return get_context_manager()
    except Exception as e:  # noqa: BLE001
        logger.debug("[harness] context_manager unavailable: %s", e)
        return None


def _try_load_memory():
    try:
        from memory_store import get_memory_store
        return get_memory_store()
    except Exception as e:  # noqa: BLE001
        logger.debug("[harness] memory_store unavailable: %s", e)
        return None


def _try_load_planner():
    try:
        from planner import Planner
        return Planner()
    except Exception as e:  # noqa: BLE001
        logger.debug("[harness] planner unavailable: %s", e)
        return None


def _try_load_observability():
    try:
        from observability import get_observability
        return get_observability()
    except Exception as e:  # noqa: BLE001
        logger.debug("[harness] observability unavailable: %s", e)
        return None


def _try_load_agent():
    """延迟构造 AIAgent。失败抛 RuntimeError 由调用方决定如何降级。"""
    from agent import AIAgent  # type: ignore
    return AIAgent()


# ============================================================
# Harness 门面
# ============================================================

class Harness:
    """通用 Agent 运行时门面。薄包装,不替换任何现有模块。"""

    def __init__(
        self,
        config: Optional[HarnessConfig] = None,
        *,
        agent: Any = None,                         # 注入自定义 agent(单测用)
        security: Any = None,
        permission: Any = None,
        sandbox_runner: Any = None,
        context_manager: Any = None,
        memory_store: Any = None,
        planner: Any = None,
        observability: Any = None,
    ) -> None:
        self.config = config or HarnessConfig()
        self.last_trace: Optional[Trace] = None

        # agent:允许注入,否则延迟加载
        self.agent = agent

        # 子模块:用 None 表示"按 config 决定是否启用";显式传入(可 None)表示"强制关闭"
        self._security_injected = security is not None
        self._permission_injected = permission is not None
        self._sandbox_injected = sandbox_runner is not None
        self._context_injected = context_manager is not None
        self._memory_injected = memory_store is not None
        self._planner_injected = planner is not None
        self._observability_injected = observability is not None

        self._security = security
        self._permission = permission
        self._sandbox = sandbox_runner
        self._context = context_manager
        self._memory = memory_store
        self._planner = planner
        self._observability = observability

    # ---------- 构造快捷方式 ----------
    @classmethod
    def from_config(cls, cfg: HarnessConfig) -> "Harness":
        return cls(config=cfg)

    # ---------- 同步入口 ----------
    def run(self, prompt: str, **kwargs) -> str:
        if not prompt or not prompt.strip():
            return "❌ 错误: 输入不能为空"
        trace = self._trace_start(prompt)
        session_id = trace.session_id

        # 前置编排:安全/权限/sandbox/planner(任意一个抛异常都被各自的 try 吞掉,只打点)
        self._security_check(prompt, trace)
        self._permission_check(prompt, trace)
        self._sandbox_evaluate(trace)
        self._planner_maybe_split(prompt, trace)

        try:
            agent = self._ensure_agent()
            output = agent.run(prompt, session_id=session_id, **kwargs)
        except Exception as e:  # noqa: BLE001
            trace.error = repr(e)
            self._trace_end(trace, output="")
            self.last_trace = trace
            return f"❌ Harness error: {e}"
        self._post_run(prompt, output, trace)
        self._trace_end(trace, output=output)
        self.last_trace = trace
        return output

    # ---------- 流式入口 ----------
    def run_stream(self, prompt: str, **kwargs) -> Iterator[str]:
        if not prompt or not prompt.strip():
            yield "❌ 错误: 输入不能为空"
            return
        trace = self._trace_start(prompt)
        session_id = trace.session_id

        # 前置编排(同步流都先打点)
        self._security_check(prompt, trace)
        self._permission_check(prompt, trace)
        self._sandbox_evaluate(trace)
        self._planner_maybe_split(prompt, trace)

        try:
            agent = self._ensure_agent()
        except Exception as e:  # noqa: BLE001
            trace.error = repr(e)
            self._trace_end(trace, output="")
            self.last_trace = trace
            yield f"❌ Harness error: {e}"
            return

        buf: List[str] = []
        try:
            for chunk in agent.run_stream(prompt, session_id=session_id, **kwargs):
                buf.append(chunk)
                yield chunk
            output = "".join(buf)
        except Exception as e:  # noqa: BLE001
            trace.error = repr(e)
            output = "".join(buf)
            self._post_run(prompt, output, trace)
            self._trace_end(trace, output=output)
            self.last_trace = trace
            return

        self._post_run(prompt, output, trace)
        self._trace_end(trace, output=output)
        self.last_trace = trace

    # ============================================================
    # 内部:orchestration
    # ============================================================

    def _ensure_agent(self):
        if self.agent is not None:
            return self.agent
        self.agent = _try_load_agent()
        return self.agent

    def _session_id(self) -> str:
        return self.config.session_id or f"harness-{uuid.uuid4().hex[:8]}"

    def _security_check(self, prompt: str, trace: Trace) -> None:
        if not self.config.enable_security:
            return
        if self._security_injected and self._security is None:
            return
        sec = self._security if self._security_injected else _try_load_security()
        if sec is None:
            return
        t0 = time.monotonic()
        try:
            res = sec.check_input(prompt)  # 约定:返回 (allowed, reason)
            allowed = bool(res[0]) if isinstance(res, tuple) else bool(res)
            status = "ok" if allowed else "fail"
            detail = {"allowed": allowed, "reason": res[1] if isinstance(res, tuple) else None}
        except Exception as e:  # noqa: BLE001
            status = "fail"
            detail = {"error": repr(e)}
        self._record_step(trace, "security", "intent_check", t0, status, detail)

    def _permission_check(self, prompt: str, trace: Trace) -> None:
        if self._permission_injected and self._permission is None:
            return
        guard = self._permission if self._permission_injected else _try_load_permission()
        if guard is None:
            return
        t0 = time.monotonic()
        try:
            # 约定:check(prompt) 返回 decision 对象/布尔
            decision = guard.check(prompt) if hasattr(guard, "check") else None
            allowed = bool(getattr(decision, "allowed", True)) if decision is not None else True
            status = "ok" if allowed else "fail"
            detail = {"allowed": allowed}
        except Exception as e:  # noqa: BLE001
            status = "fail"
            detail = {"error": repr(e)}
        self._record_step(trace, "permission", "guard_check", t0, status, detail)

    def _sandbox_evaluate(self, trace: Trace) -> None:
        runner = self._sandbox if self._sandbox_injected else _try_load_sandbox(self.config.sandbox)
        if runner is None:
            return
        t0 = time.monotonic()
        try:
            # 没有实际要执行代码,只记录 sandbox 配置已就绪
            self._record_step(
                trace, "sandbox", "policy_ready", t0, "ok",
                {"level": getattr(runner, "policy", None) and runner.policy.level.value},
            )
        except Exception as e:  # noqa: BLE001
            self._record_step(trace, "sandbox", "policy_ready", t0, "fail", {"error": repr(e)})

    def _planner_maybe_split(self, prompt: str, trace: Trace) -> None:
        if not self.config.enable_planner:
            return
        planner = self._planner if self._planner_injected else _try_load_planner()
        if planner is None:
            return
        t0 = time.monotonic()
        try:
            plan = planner.plan(prompt) if hasattr(planner, "plan") else None
            self._record_step(trace, "planner", "plan", t0, "ok",
                              {"steps": len(plan or []) if hasattr(plan, "__len__") else 0})
        except Exception as e:  # noqa: BLE001
            self._record_step(trace, "planner", "plan", t0, "fail", {"error": repr(e)})

    def _post_run(self, prompt: str, output: str, trace: Trace) -> None:
        # 1) memory 写入
        if self.config.enable_memory:
            mem = self._memory if self._memory_injected else _try_load_memory()
            if mem is not None:
                t0 = time.monotonic()
                try:
                    mem.record(session_id=trace.session_id, role="user", content=prompt)
                    mem.record(session_id=trace.session_id, role="assistant", content=output)
                    self._record_step(trace, "memory", "record_turn", t0, "ok", {})
                except Exception as e:  # noqa: BLE001
                    self._record_step(trace, "memory", "record_turn", t0, "fail", {"error": repr(e)})

        # 2) observability 上报
        if self.config.enable_observability:
            obs = self._observability if self._observability_injected else _try_load_observability()
            if obs is not None:
                t0 = time.monotonic()
                # 延迟导入,避免冷启动开销
                from harness_observability import record_metric as _rec, record_event as _evt
                tags = {"session_id": trace.session_id, **self.config.extra_tags}
                ok1 = _rec(obs, "harness.run.complete", 1.0, tags=tags,
                           help_text="Harness 完成的 run 计数")
                ok2 = _rec(obs, "harness.run.output_len", float(len(output)), tags=tags,
                           help_text="Harness 输出的字符长度")
                # 业务事件:每个 run 发一条,便于订阅/回放
                _evt(obs, "harness.run.completed", "harness",
                     trace_id=trace.session_id,
                     payload={"prompt": prompt[:200], "output_len": len(output),
                              "passed": "true"})
                self._record_step(
                    trace, "observability", "record_metric", t0,
                    "ok" if (ok1 and ok2) else "fail",
                    {"complete_ok": ok1, "output_len_ok": ok2},
                )

    # ============================================================
    # 内部:trace helper
    # ============================================================

    def _trace_start(self, prompt: str) -> Trace:
        return Trace(
            session_id=self._session_id(),
            prompt=prompt,
            started_at=datetime.utcnow().isoformat(timespec="seconds"),
        )

    def _trace_end(self, trace: Trace, output: str) -> None:
        trace.output = output
        trace.finished_at = datetime.utcnow().isoformat(timespec="seconds")

    def _record_step(self, trace: Trace, stage: str, name: str,
                     t0: float, status: str, detail: Dict[str, Any]) -> None:
        trace.steps.append(TraceStep(
            stage=stage, name=name, started_at=t0,
            duration_ms=(time.monotonic() - t0) * 1000.0,
            status=status, detail=detail,
        ))

    # ---------- 对外观察 ----------
    @property
    def enabled_modules(self) -> Dict[str, bool]:
        """返回各子系统当前启用状态(便于 dashboard 展示)。"""
        return {
            "agent": self.agent is not None,
            "security": self.config.enable_security,
            "permission": not (self._permission_injected and self._permission is None),
            "sandbox": self.config.sandbox != "off",
            "memory": self.config.enable_memory,
            "planner": self.config.enable_planner,
            "observability": self.config.enable_observability,
        }


__all__ = ["Harness", "HarnessConfig", "Trace", "TraceStep"]
# 注意:harness_observability 模块也可单独导入供测试使用