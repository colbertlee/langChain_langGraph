"""
v2.0 slim — negotiation.py 冻结层

老 negotiation.py 的 Auction / Bid / NegotiationParticipantMixin 全部冻结。
本模块只保留 import 路径，调用时统一抛 NotImplementedError。
"""
from __future__ import annotations

from .frozen import frozen


@frozen("negotiate")
def negotiate(*args, **kwargs):
    """negotiation 入口（已冻结于 v2.0 slim）。"""
    pass


@frozen("AuctionManager")
class AuctionManager:
    pass


@frozen("Bid")
class Bid:
    pass


@frozen("NegotiationParticipantMixin")
class NegotiationParticipantMixin:
    pass