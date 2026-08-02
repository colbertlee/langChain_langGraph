"""
Headless Agent 事件协议（MVP）。

目标
----
给 headless 调用方一个稳定的、与 Web/CLI 无关的事件枚举与数据类，
便于脚本/CI/嵌入式场景统一消费。

事件种类（共 7 类）
------------------
TOKEN                文本增量
TOOL_CALL            LLM 决定调用工具
TOOL_RESULT          工具执行结果
PERMISSION_REQUEST   触发 HITL 决策请求
PERMISSION_RESPONSE  HITL 决策结果
ERROR                异常
DONE                 终止事件（永远会发出，data 含 final_text）

设计要点
--------
- HeadlessEvent 是不可变数据类（dataclass + frozen=False 以便测试时替换）；
- timestamp 默认当前时间（time.time()）；
- 不依赖任何 Web/IO 框架（不引入 fastapi / uvicorn / websockets）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class HeadlessEventType(str, Enum):
    """Headless 事件类型枚举。继承 str 以便直接 json.dumps。"""

    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    PERMISSION_REQUEST = "permission_request"
    PERMISSION_RESPONSE = "permission_response"
    ERROR = "error"
    DONE = "done"


@dataclass
class HeadlessEvent:
    """一条 headless 事件。

    Attributes:
        type: 事件类型，参见 ``HeadlessEventType``。
        data: 事件负载（不同 type 含义不同，详见模块 docstring）。
        timestamp: 事件产生时刻（秒，``time.time()``）。
    """

    type: HeadlessEventType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    # ---- 便利构造器（避免各调用点重复写 dict） ----

    @classmethod
    def token(cls, delta: str) -> "HeadlessEvent":
        return cls(type=HeadlessEventType.TOKEN, data={"delta": delta})

    @classmethod
    def tool_call(cls, name: str, args: Dict[str, Any]) -> "HeadlessEvent":
        return cls(type=HeadlessEventType.TOOL_CALL, data={"name": name, "args": args})

    @classmethod
    def tool_result(cls, name: str, result: Any = None, error: str | None = None) -> "HeadlessEvent":
        return cls(
            type=HeadlessEventType.TOOL_RESULT,
            data={"name": name, "result": result, "error": error},
        )

    @classmethod
    def permission_request(cls, tool: str, args: Dict[str, Any]) -> "HeadlessEvent":
        return cls(
            type=HeadlessEventType.PERMISSION_REQUEST,
            data={"tool": tool, "args": args},
        )

    @classmethod
    def permission_response(cls, tool: str, approved: bool, reason: str = "") -> "HeadlessEvent":
        return cls(
            type=HeadlessEventType.PERMISSION_RESPONSE,
            data={"tool": tool, "approved": approved, "reason": reason},
        )

    @classmethod
    def error(cls, message: str, traceback: str | None = None) -> "HeadlessEvent":
        return cls(
            type=HeadlessEventType.ERROR,
            data={"message": message, "traceback": traceback},
        )

    @classmethod
    def done(cls, final_text: str, usage: Dict[str, Any] | None = None) -> "HeadlessEvent":
        return cls(
            type=HeadlessEventType.DONE,
            data={"final_text": final_text, "usage": usage or {}},
        )


__all__ = ["HeadlessEventType", "HeadlessEvent"]