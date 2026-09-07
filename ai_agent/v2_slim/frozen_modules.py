"""
v2.0 slim — 冻结模块的中央占位

ab_testing / adaptive_threshold / rate_limit / distributed_bus / mcp_server 等
被裁剪模块的"门面"。

历史：v2.0.9 时期曾设想通过 config.LEGACY_MODE=True 切换回原模块。
v2.10 起 LEGACY_MODE 已删除为常量 False，本模块的占位 stub 永久生效。
原被裁剪模块文件仍保留在 ai_agent/ 根目录（未删除），如需恢复可手动 import。
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
