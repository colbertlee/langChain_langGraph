"""
v2.0 slim 实验性工具（已被裁剪，保留 stub 供回归测试发现调用点）

被裁剪工具清单：
- etf_analyzer      ETF 分析
- github_pr_review  GitHub PR 审查
- market_replay     行情回放
"""
from ..frozen import frozen


@frozen("etf_analyzer")
def etf_analyzer(*args, **kwargs):
    """ETF 分析工具（已冻结于 v2.0 slim）。"""
    pass


@frozen("github_pr_review")
def github_pr_review(*args, **kwargs):
    """GitHub PR 审查工具（已冻结于 v2.0 slim）。"""
    pass


@frozen("market_replay")
def market_replay(*args, **kwargs):
    """行情回放工具（已冻结于 v2.0 slim）。"""
    pass