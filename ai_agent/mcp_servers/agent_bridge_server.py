"""
Agent Bridge MCP Server —— stdio 模式

把 ai_agent 现有的能力（capability / skill / ETF / RAG）以 MCP 协议再次暴露，
让外部 MCP 客户端（Claude Desktop / Cursor / 另一个 agent）能通过 stdio 调用本项目的能力。

与 demo_server.py 的区别：
    - demo_server.py     提供一组与 ai_agent 无关的示例工具，用来学协议
    - agent_bridge.py    把 ai_agent 已有能力打包成 MCP 工具，体现"反向暴露"

提供工具：
    list_capabilities   列出 ai_agent 已注册的能力（worker / load balancer）
    list_skills         列出 Skill 系统中已注册的 Skill
    run_etf_info        调 tools.get_etf_info(code)
    query_knowledge     调 tools.query_knowledge_base(query)，依赖全局 RAG 实例
"""
import asyncio
import json
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


SERVER_NAME = "ai-agent-bridge"
SERVER_VERSION = "1.0.0"


def _safe_call(func, *args, **kwargs):
    """统一异常包装：业务异常 → TextContent，便于在 JSON-RPC 中传递"""
    try:
        result = func(*args, **kwargs)
        if not isinstance(result, str):
            result = json.dumps(result, ensure_ascii=False, default=str)
        return TextContent(type="text", text=result)
    except Exception as e:
        return TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")


def _make_server() -> Server:
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="list_capabilities",
                description="列出 ai_agent 已注册的 Capability（worker 列表 + 负载均衡快照）",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="list_skills",
                description="列出 Skill 系统中已注册的 Skill 名称 / 描述 / 分类",
                inputSchema={"type": "object", "properties": {}},
            ),
            Tool(
                name="run_etf_info",
                description="查询 ETF 基本信息（名称 / 规模 / 净值 等），参数为 ETF 代码（如 510300）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "etf_code": {"type": "string", "description": "ETF 代码"},
                    },
                    "required": ["etf_code"],
                },
            ),
            Tool(
                name="query_knowledge",
                description="查询本地知识库（RAG）。需要先在主进程里加载文档，否则返回'未初始化'",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "自然语言问题"},
                    },
                    "required": ["query"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        if name == "list_capabilities":
            try:
                from capability import get_capability_registry, get_load_balancer
                reg = get_capability_registry()
                lb = get_load_balancer()
                # 不强制触发网络，只返回 registry 里已经注册的 worker
                workers = list(getattr(reg, "workers", {}).keys()) if hasattr(reg, "workers") else []
                snapshot = {
                    "worker_count": len(workers),
                    "workers": workers,
                    "lb_strategy": str(getattr(lb, "strategy", "")),
                }
                return [TextContent(type="text", text=json.dumps(snapshot, ensure_ascii=False))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]

        if name == "list_skills":
            try:
                from skills import get_skill_manager
                mgr = get_skill_manager()
                info = []
                for sk in mgr.registry.list_all():
                    info.append({
                        "name": sk.name,
                        "category": getattr(sk, "category", ""),
                        "enabled": getattr(sk, "enabled", True),
                        "description": getattr(sk, "description", ""),
                    })
                return [TextContent(type="text", text=json.dumps(info, ensure_ascii=False))]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]

        if name == "run_etf_info":
            try:
                from tools import get_etf_info
                return [_safe_call(get_etf_info, arguments["etf_code"])]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]

        if name == "query_knowledge":
            try:
                from tools import query_knowledge_base
                return [_safe_call(query_knowledge_base, arguments["query"])]
            except Exception as e:
                return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]

        return [TextContent(type="text", text=f"Error: unknown tool '{name}'")]

    return server


async def _run() -> None:
    server = _make_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()