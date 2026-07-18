"""
MCP Server - 标准 Model Context Protocol 服务器

提供 MCP 协议支持，连接外部服务和工具
"""
import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

# 全局单例实例
_mcp_tool_registry_instance = None

def get_mcp_tool_registry():
    """获取工具注册表单例"""
    global _mcp_tool_registry_instance
    if _mcp_tool_registry_instance is None:
        _mcp_tool_registry_instance = {
            "tools": {}
        }
    return _mcp_tool_registry_instance


# ==================== MCP 类型定义 ====================

@dataclass
class MCPResource:
    """MCP 资源"""
    uri: str
    name: str
    description: str = ""
    mime_type: str = "text/plain"

@dataclass
class MCPTool:
    """MCP 工具定义"""
    name: str
    description: str
    input_schema: Dict[str, Any]

@dataclass
class MCPToolResult:
    """MCP 工具执行结果"""
    content: List[Dict[str, Any]]
    is_error: bool = False


# ==================== 工具注册表 ====================

class MCPToolRegistry:
    """MCP 工具注册表"""
    
    @staticmethod
    def register(name: str, description: str, input_schema: Dict[str, Any], 
                 handler: callable, category: str = "general"):
        """
        注册 MCP 工具
        
        Args:
            name: 工具名称
            description: 工具描述
            input_schema: 输入参数 schema (JSON Schema 格式)
            handler: 处理函数
            category: 分类 (general/file/web/data/etc.)
        """
        registry = get_mcp_tool_registry()
        
        tool = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema
        )
        
        if category not in registry["tools"]:
            registry["tools"][category] = {}
        
        registry["tools"][category][name] = {
            "tool": tool,
            "handler": handler
        }
    
    @staticmethod
    def get_all_tools() -> Dict[str, Dict[str, Any]]:
        """获取所有工具"""
        return get_mcp_tool_registry()["tools"]
    
    @staticmethod
    def get_tools_by_category(category: str) -> Dict[str, Any]:
        """按分类获取工具"""
        return get_mcp_tool_registry()["tools"].get(category, {})
    
    @staticmethod
    def list_categories() -> List[str]:
        """列出所有分类"""
        return list(get_mcp_tool_registry()["tools"].keys())


# ==================== MCP 服务器 ====================

class MCPServer:
    """MCP 服务器核心类"""
    
    def __init__(self, name: str = "ai-agent", version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.resources: Dict[str, MCPResource] = {}
        self.tools: Dict[str, MCPTool] = {}
        self.tool_handlers: Dict[str, callable] = {}
        
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
    
    # ==================== 资源管理 ====================
    
    def add_resource(self, resource: MCPResource):
        """添加资源"""
        self.resources[resource.uri] = resource
        self.logger.info("[MCP] Added resource: {}".format(resource.uri))
    
    def list_resources(self) -> List[Dict[str, Any]]:
        """列出所有资源"""
        return [
            {
                "uri": r.uri,
                "name": r.name,
                "description": r.description,
                "mimeType": r.mime_type
            }
            for r in self.resources.values()
        ]
    
    # ==================== 工具管理 ====================
    
    def add_tool(self, tool: MCPTool, handler: callable):
        """
        添加工具
        
        Args:
            tool: 工具定义
            handler: 处理函数，接收参数字典，返回字符串或 MCPToolResult
        """
        self.tools[tool.name] = tool
        self.tool_handlers[tool.name] = handler
        self.logger.info("[MCP] Added tool: {}".format(tool.name))
    
    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.input_schema
            }
            for t in self.tools.values()
        ]
    
    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> MCPToolResult:
        """
        调用工具
        
        Args:
            name: 工具名称
            arguments: 参数字典
        
        Returns:
            MCPToolResult: 工具执行结果
        """
        if name not in self.tool_handlers:
            return MCPToolResult(
                content=[{"type": "text", "text": "Tool not found: {}".format(name)}],
                is_error=True
            )
        
        try:
            handler = self.tool_handlers[name]
            result = handler(arguments)
            
            if isinstance(result, MCPToolResult):
                return result
            
            return MCPToolResult(
                content=[{"type": "text", "text": str(result)}],
                is_error=False
            )
        except Exception as e:
            self.logger.error("[MCP] Tool error: {} - {}".format(name, str(e)))
            return MCPToolResult(
                content=[{"type": "text", "text": "Error: {}".format(str(e))}],
                is_error=True
            )
    
    # ==================== MCP 协议方法 ====================
    
    async def handle_request(self, method: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        处理 MCP 请求
        
        Args:
            method: 方法名 (initialize, tools/list, tools/call, resources/list, etc.)
            params: 参数
        
        Returns:
            响应数据
        """
        params = params or {}
        
        if method == "initialize":
            return self._handle_initialize(params)
        elif method == "tools/list":
            return self._handle_tools_list()
        elif method == "tools/call":
            return await self._handle_tools_call(params)
        elif method == "resources/list":
            return self._handle_resources_list()
        elif method == "resources/read":
            return self._handle_resources_read(params)
        else:
            return {"error": "Unknown method: {}".format(method)}
    
    def _handle_initialize(self, params: Dict) -> Dict:
        """处理初始化请求"""
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True}
            },
            "serverInfo": {
                "name": self.name,
                "version": self.version
            }
        }
    
    def _handle_tools_list(self) -> Dict:
        """处理工具列表请求"""
        return {"tools": self.list_tools()}
    
    async def _handle_tools_call(self, params: Dict) -> Dict:
        """处理工具调用请求"""
        name = params.get("name", "")
        arguments = params.get("arguments", {})
        
        result = await self.call_tool(name, arguments)
        
        return {
            "content": result.content,
            "isError": result.is_error
        }
    
    def _handle_resources_list(self) -> Dict:
        """处理资源列表请求"""
        return {"resources": self.list_resources()}
    
    def _handle_resources_read(self, params: Dict) -> Dict:
        """处理资源读取请求"""
        uri = params.get("uri", "")
        
        if uri in self.resources:
            resource = self.resources[uri]
            return {
                "contents": [{
                    "uri": uri,
                    "mimeType": resource.mime_type,
                    "text": ""
                }]
            }
        
        return {"error": "Resource not found: {}".format(uri)}


# 全局 MCP 服务器实例
_mcp_server_instance = None

def get_mcp_server() -> MCPServer:
    """获取全局 MCP 服务器实例"""
    global _mcp_server_instance
    if _mcp_server_instance is None:
        _mcp_server_instance = MCPServer(name="ai-agent-mcp", version="1.0.0")
    return _mcp_server_instance

def create_mcp_server(name: str = "ai-agent") -> MCPServer:
    """创建新的 MCP 服务器"""
    return MCPServer(name=name, version="1.0.0")
