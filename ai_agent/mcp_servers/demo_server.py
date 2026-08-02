"""
Demo MCP Server —— stdio 模式

一组简单的示例工具，用来演示如何用官方 mcp Python SDK 写一个 stdio MCP server。
供 ai_agent 学习 / 测试 / 调试 MCP 协议使用。

启动方式：
    python -m ai_agent.mcp_servers.demo_server
或在 mcp_config.json 里：
    {"command": "python", "args": ["-m", "ai_agent.mcp_servers.demo_server"]}

提供工具：
    echo           原样回显
    reverse_text   字符串反转
    sha256_hash    计算 SHA-256
    random_number  生成随机整数
    word_count     统计词数 / 字符数 / 行数
"""
import asyncio
import hashlib
import random
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent


SERVER_NAME = "demo-mcp-server"
SERVER_VERSION = "1.0.0"


def _make_server() -> Server:
    """构造 MCP Server 实例 + 注册工具"""
    server = Server(SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name="echo",
                description="原样回显传入的字符串",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要回显的文本"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="reverse_text",
                description="反转字符串",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要反转的字符串"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="sha256_hash",
                description="计算字符串的 SHA-256 十六进制摘要",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要哈希的内容"},
                    },
                    "required": ["text"],
                },
            ),
            Tool(
                name="random_number",
                description="在 [min, max] 区间生成一个随机整数（包含两端）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "min": {"type": "integer", "description": "下界", "default": 0},
                        "max": {"type": "integer", "description": "上界", "default": 100},
                    },
                },
            ),
            Tool(
                name="word_count",
                description="统计文本的字符数 / 词数 / 行数",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "要统计的文本"},
                    },
                    "required": ["text"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        try:
            if name == "echo":
                return [TextContent(type="text", text=arguments["text"])]

            if name == "reverse_text":
                return [TextContent(type="text", text=arguments["text"][::-1])]

            if name == "sha256_hash":
                h = hashlib.sha256(arguments["text"].encode("utf-8")).hexdigest()
                return [TextContent(type="text", text=h)]

            if name == "random_number":
                lo = int(arguments.get("min", 0))
                hi = int(arguments.get("max", 100))
                if lo > hi:
                    return [TextContent(type="text", text=f"Error: min({lo}) > max({hi})")]
                return [TextContent(type="text", text=str(random.randint(lo, hi)))]

            if name == "word_count":
                text = arguments["text"]
                lines = text.count("\n") + (0 if text.endswith("\n") else 1) if text else 0
                chars = len(text)
                words = len(text.split())
                msg = f"chars={chars} words={words} lines={lines}"
                return [TextContent(type="text", text=msg)]

            return [TextContent(type="text", text=f"Error: unknown tool '{name}'")]

        except Exception as e:
            return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]

    return server


async def _run() -> None:
    """stdio 入口"""
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