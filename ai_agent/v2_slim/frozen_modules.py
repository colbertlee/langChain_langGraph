"""
v2.0 slim — 冻结模块的中央占位

ab_testing / adaptive_threshold / rate_limit / distributed_bus / mcp_server 等
被裁剪模块的"门面"。

为什么不直接修改原文件？
→ 用户决策是"绝对不碰核心 + LEGACY 完整保留"。原文件保留以便 config.LEGACY_MODE=True
  时继续工作；本模块仅作为发现"被冻结调用点"的统一入口。
"""
from __future__ import annotations

from .frozen import frozen


# —— ab_testing ——
@frozen("ab_test")
def ab_test(*args, **kwargs):
    pass


# —— adaptive_threshold ——
@frozen("adaptive_threshold")
def adaptive_threshold(*args, **kwargs):
    pass


# —— rate_limit ——
@frozen("rate_limit")
def rate_limit(*args, **kwargs):
    pass


# —— distributed_bus ——
@frozen("distributed_bus_publish")
def distributed_bus_publish(*args, **kwargs):
    pass


@frozen("distributed_bus_subscribe")
def distributed_bus_subscribe(*args, **kwargs):
    pass


# —— mcp_server ——
@frozen("mcp_register")
def mcp_register(*args, **kwargs):
    pass


@frozen("mcp_invoke")
def mcp_invoke(*args, **kwargs):
    pass