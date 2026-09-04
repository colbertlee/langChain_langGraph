"""
ai_agent 包入口（v2.0 slim）

将 ai_agent 标记为 Python 包，使 `from v2_slim.tools_v2 import ...`
和 `from ai_agent.v2_slim.tools_v2 import ...` 两种导入方式都能工作。

模块顶层不应放任何重逻辑（避免循环引用 + 导入成本）。
"""
__version__ = "2.0.0-slim"
