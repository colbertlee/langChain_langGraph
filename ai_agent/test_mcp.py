"""
MCP 功能测试
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_mcp_server():
    """测试 MCP 服务器"""
    print("=" * 60)
    print("Testing MCP Server")
    print("=" * 60)
    
    try:
        from mcp_server import MCPServer, MCPTool, get_mcp_server
        
        # 创建服务器
        server = MCPServer(name="test-server", version="1.0.0")
        print("[OK] MCP Server created")
        
        # 添加工具
        tool = MCPTool(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}}
        )
        server.add_tool(tool, lambda args: "Hello from test tool")
        print("[OK] Tool added")
        
        # 列出工具
        tools = server.list_tools()
        print("[OK] Listed {} tools".format(len(tools)))
        
        return True
        
    except Exception as e:
        print("[ERROR] {}".format(str(e)))
        import traceback
        traceback.print_exc()
        return False


def test_mcp_tools():
    """测试 MCP 工具集"""
    print("\n" + "=" * 60)
    print("Testing MCP Tools")
    print("=" * 60)
    
    try:
        from mcp_tools import register_all_mcp_tools, MCPToolRegistry
        
        # 注册所有工具
        register_all_mcp_tools()
        print("[OK] All tools registered")
        
        # 列出分类
        categories = MCPToolRegistry.list_categories()
        print("[OK] Categories: {}".format(categories))
        
        # 列出工具
        all_tools = MCPToolRegistry.get_all_tools()
        total = sum(len(tools) for tools in all_tools.values())
        print("[OK] Total tools: {}".format(total))
        
        # 测试文件工具
        from mcp_tools import handle_current_time
        result = handle_current_time({})
        print("[OK] current_time tool: {}".format(result[:20]))
        
        # 测试 JSON 工具
        from mcp_tools import handle_json_parse
        result = handle_json_parse({"json": '{"key": "value"}'})
        print("[OK] json_parse tool: {}".format(result[:30]))
        
        return True
        
    except Exception as e:
        print("[ERROR] {}".format(str(e)))
        import traceback
        traceback.print_exc()
        return False


def test_mcp_integration():
    """测试 MCP 集成"""
    print("\n" + "=" * 60)
    print("Testing MCP Integration")
    print("=" * 60)
    
    try:
        from mcp_server import get_mcp_server
        from mcp_tools import setup_mcp_server, MCPToolRegistry
        
        # 设置 MCP 服务器
        setup_mcp_server()
        print("[OK] MCP server setup complete")
        
        # 获取服务器
        server = get_mcp_server()
        
        # 列出所有工具
        tools = server.list_tools()
        print("[OK] Server has {} tools".format(len(tools)))
        
        # 测试工具调用
        import asyncio
        
        async def test_call():
            result = await server.call_tool("current_time", {})
            print("[OK] Tool call result: {}".format(str(result.content)[:50]))
        
        asyncio.run(test_call())
        
        return True
        
    except Exception as e:
        print("[ERROR] {}".format(str(e)))
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n")
    
    success = True
    success = test_mcp_server() and success
    success = test_mcp_tools() and success
    success = test_mcp_integration() and success
    
    print("\n" + "=" * 60)
    if success:
        print("All MCP tests passed!")
    else:
        print("Some tests failed!")
    print("=" * 60)
    
    sys.exit(0 if success else 1)
