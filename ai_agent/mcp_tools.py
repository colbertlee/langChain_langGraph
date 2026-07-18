"""
MCP 工具集 - 标准 MCP 协议工具

定义可通过 MCP 协议调用的外部工具
"""
import json
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

from mcp_server import MCPToolRegistry, get_mcp_server, MCPTool, MCPToolResult


# ==================== 文件系统工具 ====================

def handle_read_file(args: Dict[str, Any]) -> str:
    """读取文件内容"""
    file_path = args.get("path", "")
    
    if not file_path:
        return "Error: path is required"
    
    if ".." in file_path or file_path.startswith("/"):
        return "Error: Access denied"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) > 5000:
                return content[:5000] + "\n... (truncated)"
            return content
    except FileNotFoundError:
        return "Error: File not found"
    except Exception as e:
        return "Error: {}".format(str(e))


def handle_write_file(args: Dict[str, Any]) -> str:
    """写入文件内容"""
    file_path = args.get("path", "")
    content = args.get("content", "")
    
    if not file_path:
        return "Error: path is required"
    
    if ".." in file_path or file_path.startswith("/"):
        return "Error: Access denied"
    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return "Success: Written to {}".format(file_path)
    except Exception as e:
        return "Error: {}".format(str(e))


def handle_list_directory(args: Dict[str, Any]) -> str:
    """列出目录内容"""
    path = args.get("path", ".")
    
    if ".." in path or path.startswith("/"):
        return "Error: Access denied"
    
    try:
        items = os.listdir(path)
        result = "Directory: {}\n".format(path)
        result += "-" * 40 + "\n"
        for item in sorted(items):
            full_path = os.path.join(path, item)
            if os.path.isdir(full_path):
                result += "[DIR]  {}\n".format(item)
            else:
                size = os.path.getsize(full_path)
                result += "[FILE] {} ({} bytes)\n".format(item, size)
        return result
    except Exception as e:
        return "Error: {}".format(str(e))


# ==================== 网络工具 ====================

def handle_curl(args: Dict[str, Any]) -> str:
    """发送 HTTP 请求"""
    import requests
    
    url = args.get("url", "")
    method = args.get("method", "GET").upper()
    headers = args.get("headers", {})
    data = args.get("data", {})
    
    if not url:
        return "Error: url is required"
    
    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, headers=headers, timeout=10)
        else:
            return "Error: Unsupported method: {}".format(method)
        
        return "Status: {}\nHeaders: {}\nBody: {}".format(
            response.status_code,
            dict(response.headers),
            response.text[:1000]
        )
    except Exception as e:
        return "Error: {}".format(str(e))


def handle_whoami(args: Dict[str, Any]) -> str:
    """获取当前用户信息"""
    import getpass
    import platform
    
    return json.dumps({
        "username": getpass.getuser(),
        "hostname": platform.node(),
        "platform": platform.system(),
        "python_version": platform.python_version()
    }, indent=2)


# ==================== 开发工具 ====================

def handle_git_status(args: Dict[str, Any]) -> str:
    """获取 Git 状态"""
    import subprocess
    
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout if result.stdout else "No changes"
    except Exception as e:
        return "Error: {}".format(str(e))


def handle_git_log(args: Dict[str, Any]) -> str:
    """获取 Git 提交历史"""
    import subprocess
    
    limit = args.get("limit", 10)
    
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-{}".format(limit)],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout if result.stdout else "No commits"
    except Exception as e:
        return "Error: {}".format(str(e))


def handle_docker_ps(args: Dict[str, Any]) -> str:
    """列出运行中的容器"""
    import subprocess
    
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout if result.stdout else "Docker not available"
    except Exception as e:
        return "Error: {}".format(str(e))


# ==================== 系统工具 ====================

def handle_system_info(args: Dict[str, Any]) -> str:
    """获取系统信息"""
    import platform
    import psutil
    
    return json.dumps({
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "cpu_count": psutil.cpu_count(),
        "memory_total": psutil.virtual_memory().total,
        "memory_available": psutil.virtual_memory().available,
        "disk_usage": dict(psutil.disk_usage('/'))
    }, indent=2)


def handle_process_list(args: Dict[str, Any]) -> str:
    """列出运行中的进程"""
    import psutil
    
    limit = args.get("limit", 10)
    processes = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            processes.append(proc.info)
        except:
            pass
    
    # 按 CPU 使用率排序
    processes.sort(key=lambda x: x.get('cpu_percent', 0), reverse=True)
    
    result = "Top {} Processes:\n".format(limit)
    result += "-" * 60 + "\n"
    for p in processes[:limit]:
        result += "PID: {} | Name: {} | CPU: {}% | Mem: {}%\n".format(
            p['pid'], p['name'], p['cpu_percent'], p['memory_percent']
        )
    
    return result


# ==================== 数据工具 ====================

def handle_json_parse(args: Dict[str, Any]) -> str:
    """解析 JSON"""
    json_str = args.get("json", "")
    pretty = args.get("pretty", True)
    
    if not json_str:
        return "Error: json is required"
    
    try:
        data = json.loads(json_str)
        return json.dumps(data, indent=2 if pretty else None, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return "Error: Invalid JSON - {}".format(str(e))


def handle_json_query(args: Dict[str, Any]) -> str:
    """查询 JSON 数据 (使用 JMESPath)"""
    import jmespath
    
    json_str = args.get("json", "")
    query = args.get("query", "")
    
    if not json_str or not query:
        return "Error: json and query are required"
    
    try:
        data = json.loads(json_str)
        result = jmespath.search(query, data)
        return json.dumps(result, indent=2, ensure_ascii=False)
    except Exception as e:
        return "Error: {}".format(str(e))


# ==================== 时间工具 ====================

def handle_current_time(args: Dict[str, Any]) -> str:
    """获取当前时间"""
    format_str = args.get("format", "%Y-%m-%d %H:%M:%S")
    return datetime.now().strftime(format_str)


def handle_timestamp(args: Dict[str, Any]) -> str:
    """时间戳转换"""
    timestamp = args.get("timestamp", None)
    to_format = args.get("format", "%Y-%m-%d %H:%M:%S")
    
    if timestamp:
        dt = datetime.fromtimestamp(int(timestamp))
        return dt.strftime(to_format)
    else:
        return str(int(datetime.now().timestamp()))


# ==================== 注册所有 MCP 工具 ====================

def register_all_mcp_tools():
    """注册所有 MCP 工具到注册表"""
    
    # 文件系统工具
    MCPToolRegistry.register(
        name="file_read",
        description="读取文件内容",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"}
            },
            "required": ["path"]
        },
        handler=handle_read_file,
        category="file"
    )
    
    MCPToolRegistry.register(
        name="file_write",
        description="写入内容到文件",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "文件内容"}
            },
            "required": ["path", "content"]
        },
        handler=handle_write_file,
        category="file"
    )
    
    MCPToolRegistry.register(
        name="directory_list",
        description="列出目录内容",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "目录路径"}
            }
        },
        handler=handle_list_directory,
        category="file"
    )
    
    # 网络工具
    MCPToolRegistry.register(
        name="http_request",
        description="发送 HTTP 请求",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "请求 URL"},
                "method": {"type": "string", "enum": ["GET", "POST"], "description": "HTTP 方法"},
                "headers": {"type": "object", "description": "请求头"},
                "data": {"type": "object", "description": "POST 请求数据"}
            },
            "required": ["url"]
        },
        handler=handle_curl,
        category="web"
    )
    
    MCPToolRegistry.register(
        name="whoami",
        description="获取当前用户信息",
        input_schema={"type": "object", "properties": {}},
        handler=handle_whoami,
        category="system"
    )
    
    # 开发工具
    MCPToolRegistry.register(
        name="git_status",
        description="获取 Git 仓库状态",
        input_schema={"type": "object", "properties": {}},
        handler=handle_git_status,
        category="development"
    )
    
    MCPToolRegistry.register(
        name="git_log",
        description="获取 Git 提交历史",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "显示数量", "default": 10}
            }
        },
        handler=handle_git_log,
        category="development"
    )
    
    MCPToolRegistry.register(
        name="docker_ps",
        description="列出运行中的 Docker 容器",
        input_schema={"type": "object", "properties": {}},
        handler=handle_docker_ps,
        category="development"
    )
    
    # 系统工具
    MCPToolRegistry.register(
        name="system_info",
        description="获取系统信息",
        input_schema={"type": "object", "properties": {}},
        handler=handle_system_info,
        category="system"
    )
    
    MCPToolRegistry.register(
        name="process_list",
        description="列出运行中的进程",
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "显示数量", "default": 10}
            }
        },
        handler=handle_process_list,
        category="system"
    )
    
    # 数据工具
    MCPToolRegistry.register(
        name="json_parse",
        description="解析 JSON 字符串",
        input_schema={
            "type": "object",
            "properties": {
                "json": {"type": "string", "description": "JSON 字符串"},
                "pretty": {"type": "boolean", "description": "格式化输出", "default": True}
            },
            "required": ["json"]
        },
        handler=handle_json_parse,
        category="data"
    )
    
    MCPToolRegistry.register(
        name="json_query",
        description="使用 JMESPath 查询 JSON",
        input_schema={
            "type": "object",
            "properties": {
                "json": {"type": "string", "description": "JSON 字符串"},
                "query": {"type": "string", "description": "JMESPath 查询表达式"}
            },
            "required": ["json", "query"]
        },
        handler=handle_json_query,
        category="data"
    )
    
    # 时间工具
    MCPToolRegistry.register(
        name="current_time",
        description="获取当前时间",
        input_schema={
            "type": "object",
            "properties": {
                "format": {"type": "string", "description": "时间格式", "default": "%Y-%m-%d %H:%M:%S"}
            }
        },
        handler=handle_current_time,
        category="utility"
    )
    
    MCPToolRegistry.register(
        name="timestamp_convert",
        description="时间戳转换",
        input_schema={
            "type": "object",
            "properties": {
                "timestamp": {"type": "integer", "description": "Unix 时间戳"},
                "format": {"type": "string", "description": "输出格式", "default": "%Y-%m-%d %H:%M:%S"}
            }
        },
        handler=handle_timestamp,
        category="utility"
    )


def setup_mcp_server() -> None:
    """设置并初始化 MCP 服务器"""
    server = get_mcp_server()
    
    # 注册所有工具
    register_all_mcp_tools()
    
    # 将注册表中的工具添加到服务器
    for category, tools in MCPToolRegistry.get_all_tools().items():
        for name, data in tools.items():
            server.add_tool(data["tool"], data["handler"])
    
    print("[MCP] Server initialized with {} categories".format(
        len(MCPToolRegistry.list_categories())
    ))
