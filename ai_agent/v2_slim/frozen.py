"""
v2.0 slim 冻结注册表

所有被裁剪的能力（ab_testing / adaptive_threshold / rate_limit /
negotiation / parallel / hierarchical / fanout / mcp_tools / ...）
通过本模块统一返回 NotImplementedError，保留调用点以便回归测试发现。
"""
from typing import Callable, Any
import warnings


_FROZEN_NAMES = {
    # —— 多 Agent 裁剪 ——
    "create_parallel_agent",
    "create_hierarchical_agent",
    "create_fanout_agent",
    "negotiate",
    # —— 实验性工具 ——
    "etf_analyzer",
    "github_pr_review",
    "market_replay",
    # —— 安全/可观测/性能 合并 ——
    "ab_test",
    "adaptive_threshold",
    "rate_limit",
    "json_log_emit",
    "monitor_record",
    "observability_span",
    # —— 分布式总线（冻结） ——
    "distributed_bus_publish",
    "distributed_bus_subscribe",
    # —— MCP（冻结） ——
    "mcp_register",
    "mcp_invoke",
}


class _FrozenDecorator:
    """frozen() 返回的装饰器对象。

    PEP 318 语义：`@deco(args)` 实际是 `fn = deco(args)(fn)`。
    所以 deco(args) 必须返回一个接受原函数并返回替换函数的 callable。
    本类包装这一行为，并支持直接调用场景（frozen("xxx")()）。
    """

    __slots__ = ("_name",)

    def __init__(self, name: str):
        self._name = name

    def __call__(self, *args, **kwargs):
        # 用法1：作为装饰器 @frozen("xxx")\ndef f(): ...
        if len(args) == 1 and callable(args[0]) and not kwargs:
            original = args[0]

            def _stub(*a, **kw):
                raise NotImplementedError(f"{self._name}: Frozen in v2.0 slim")

            _stub.__name__ = original.__name__
            _stub.__qualname__ = getattr(original, "__qualname__", original.__name__)
            _stub.__doc__ = (
                f"⚠️ {self._name} 已在 v2.0 slim 中冻结。\n"
                f"调用将抛出 NotImplementedError。如需恢复，请设置 "
                f"config.LEGACY_MODE=True 或迁移到 experimental/ 子模块。"
            )
            return _stub

        # 用法2：作为函数直接调用 frozen("xxx")() — 立即抛错
        raise NotImplementedError(f"{self._name}: Frozen in v2.0 slim")


def frozen(name: str):
    """装饰器/工厂：被冻结的能力统一抛 NotImplementedError。

    用法：
        @frozen("etf_analyzer")
        def etf_analyzer(...): ...

        或者直接调用：
            frozen("etf_analyzer")()
    """
    if name not in _FROZEN_NAMES:
        warnings.warn(
            f"{name} 未在 _FROZEN_NAMES 中显式注册，已按 frozen 处理。",
            stacklevel=2,
        )
    return _FrozenDecorator(name)