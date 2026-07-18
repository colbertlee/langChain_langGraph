"""
Gitee MCP 工具集

提供 Gitee API 操作能力：仓库、文件、Issue 等
Gitee API 文档: https://gitee.com/api/v5/swagger
"""
import os
import base64
from typing import Any, Dict, List, Union

import requests
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

GITEE_TOKEN = os.getenv("GITEE_TOKEN", "")
GITEE_USERNAME = os.getenv("GITEE_USERNAME", "colbertlee").lower()
GITEE_API_BASE = "https://gitee.com/api/v5"


def get_params() -> Dict[str, str]:
    """获取请求参数（包含 Token）"""
    params = {}
    if GITEE_TOKEN:
        params["access_token"] = GITEE_TOKEN
    return params


def check_error(data: Any) -> Union[str, None]:
    """检查 API 返回是否有错误"""
    if isinstance(data, dict) and data.get("message"):
        return data.get("message")
    return None


# ==================== 仓库操作 ====================

def handle_gitee_list_repos(args: Dict[str, Any]) -> str:
    """列出用户仓库"""
    username = args.get("username", GITEE_USERNAME) or GITEE_USERNAME
    per_page = args.get("per_page", 10)
    
    try:
        url = f"{GITEE_API_BASE}/user/repos"
        params = {**get_params(), "per_page": per_page}
        
        response = requests.get(url, params=params, timeout=15)
        repos = response.json()
        
        error = check_error(repos)
        if error:
            return f"Error: {error}"
        
        if not isinstance(repos, list):
            return "Error: Failed to fetch repos"
        
        if not repos:
            return f"No repos found for user: {username}"
        
        result = f"Repositories for {username}:\n"
        result += "=" * 50 + "\n"
        
        for repo in repos:
            name = repo.get("full_name", "N/A")
            desc = repo.get("description") or "N/A"
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language") or "N/A"
            private = "🔒" if repo.get("private") else "🌐"
            result += f"\n{private} {name}\n"
            result += f"  Stars: {stars} | Lang: {lang}\n"
            result += f"  {desc[:60]}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_gitee_get_repo(args: Dict[str, Any]) -> str:
    """获取仓库详情"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    
    if not owner or not repo:
        return "Error: owner and repo are required"
    
    try:
        url = f"{GITEE_API_BASE}/repos/{owner}/{repo}"
        response = requests.get(url, params=get_params(), timeout=15)
        data = response.json()
        
        error = check_error(data)
        if error:
            return f"Error: {error}"
        
        private = "🔒 私有" if data.get("private") else "🌐 公开"
        result = f"Repository: {data.get('full_name')}\n"
        result += "=" * 50 + "\n"
        result += f"类型: {private}\n"
        result += f"描述: {data.get('description') or 'N/A'}\n"
        result += f"Stars: {data.get('stargazers_count', 0)}\n"
        result += f"Forks: {data.get('forks_count', 0)}\n"
        result += f"语言: {data.get('language') or 'N/A'}\n"
        result += f"默认分支: {data.get('default_branch', 'master')}\n"
        result += f"Issues: {data.get('open_issues_count', 0)}\n"
        result += f"创建时间: {str(data.get('created_at', 'N/A'))[:10]}\n"
        result += f"最后更新: {str(data.get('pushed_at', 'N/A'))[:10]}\n"
        result += f"URL: {data.get('html_url')}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== 文件操作 ====================

def handle_gitee_list_contents(args: Dict[str, Any]) -> str:
    """列出仓库内容"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    path = args.get("path", "")
    ref = args.get("ref", "master")
    
    if not owner or not repo:
        return "Error: owner and repo are required"
    
    try:
        url = f"{GITEE_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        params = {**get_params(), "ref": ref}
        
        response = requests.get(url, params=params, timeout=15)
        contents = response.json()
        
        error = check_error(contents)
        if error:
            return f"Error: {error}"
        
        if not isinstance(contents, list):
            return "Error: Path is a file, not a directory"
        
        result = f"Contents of {owner}/{repo}/{path or '.'} ({ref}):\n"
        result += "=" * 50 + "\n"
        
        for item in contents:
            item_type = item.get("type", "file")
            name = item.get("name", "N/A")
            size = item.get("size", 0)
            if item_type == "tree":
                result += f"[DIR]  {name}/\n"
            else:
                result += f"[FILE] {name} ({size} bytes)\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_gitee_read_file(args: Dict[str, Any]) -> str:
    """读取文件内容"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    path = args.get("path", "")
    ref = args.get("ref", "master")
    
    if not owner or not repo or not path:
        return "Error: owner, repo, and path are required"
    
    try:
        url = f"{GITEE_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        params = {**get_params(), "ref": ref}
        
        response = requests.get(url, params=params, timeout=15)
        data = response.json()
        
        error = check_error(data)
        if error:
            return f"Error: {error}"
        
        content = data.get("content", "")
        if content:
            decoded = base64.b64decode(content).decode("utf-8")
            if len(decoded) > 5000:
                return decoded[:5000] + f"\n... (truncated, total {len(decoded)} chars)"
            return decoded
        
        return "Error: No content found"
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_gitee_create_file(args: Dict[str, Any]) -> str:
    """创建或更新文件"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    path = args.get("path", "")
    content = args.get("content", "")
    message = args.get("message", "Update via AI Agent")
    
    if not owner or not repo or not path or not content:
        return "Error: owner, repo, path, and content are required"
    
    try:
        url = f"{GITEE_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        
        data = {
            "access_token": GITEE_TOKEN,
            "message": message,
            "content": base64.b64encode(content.encode()).decode()
        }
        
        # 检查文件是否存在
        check_response = requests.get(url, params={"access_token": GITEE_TOKEN})
        if check_response.status_code == 200:
            sha = check_response.json().get("sha")
            data["sha"] = sha
        
        response = requests.post(url, json=data, timeout=15)
        result = response.json()
        
        if check_error(result):
            return f"Error: {result.get('message')}"
        
        return f"Success! File: {result.get('path')}\nURL: {result.get('html_url')}"
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== Issue 操作 ====================

def handle_gitee_list_issues(args: Dict[str, Any]) -> str:
    """列出 Issue"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    state = args.get("state", "open")
    per_page = args.get("per_page", 10)
    
    if not owner or not repo:
        return "Error: owner and repo are required"
    
    try:
        url = f"{GITEE_API_BASE}/repos/{owner}/{repo}/issues"
        params = {**get_params(), "state": state, "per_page": per_page}
        
        response = requests.get(url, params=params, timeout=15)
        issues = response.json()
        
        error = check_error(issues)
        if error:
            return f"Error: {error}"
        
        result = f"Issues ({state}) in {owner}/{repo}:\n"
        result += "=" * 50 + "\n"
        
        for issue in issues[:per_page]:
            num = issue.get("iid", 0)
            title = issue.get("title", "N/A")
            state_emoji = "[+]" if issue.get("state") == "open" else "[-]"
            result += f"\n#{num} {state_emoji} {title}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== 搜索操作 ====================

def handle_gitee_search_repos(args: Dict[str, Any]) -> str:
    """搜索仓库"""
    keyword = args.get("keyword", "")
    per_page = args.get("per_page", 5)
    
    if not keyword:
        return "Error: keyword is required"
    
    try:
        url = "https://gitee.com/api/v5/search/repositories"
        params = {**get_params(), "q": keyword, "per_page": per_page}
        
        response = requests.get(url, params=params, timeout=15)
        repos = response.json()
        
        error = check_error(repos)
        if error:
            return f"Error: {error}"
        
        if not repos:
            return f"No results for: {keyword}"
        
        result = f"Search results for '{keyword}':\n"
        result += "=" * 50 + "\n"
        
        for repo in repos:
            name = repo.get("full_name", "N/A")
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language") or "N/A"
            desc = repo.get("description") or "N/A"
            private = "🔒" if repo.get("private") else "🌐"
            result += f"\n{private} {name}\n"
            result += f"  Stars: {stars} | Lang: {lang}\n"
            result += f"  {desc[:60]}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== 注册所有 Gitee MCP 工具 ====================

def register_all_gitee_tools():
    """注册所有 Gitee MCP 工具"""
    from mcp_tools import MCPToolRegistry
    
    MCPToolRegistry.register(
        name="gitee_list_repos",
        description="列出 Gitee 用户仓库",
        input_schema={
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "per_page": {"type": "integer", "default": 10}
            }
        },
        handler=handle_gitee_list_repos,
        category="gitee"
    )
    
    MCPToolRegistry.register(
        name="gitee_get_repo",
        description="获取 Gitee 仓库详情",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"}
            },
            "required": ["owner", "repo"]
        },
        handler=handle_gitee_get_repo,
        category="gitee"
    )
    
    MCPToolRegistry.register(
        name="gitee_list_contents",
        description="列出 Gitee 仓库目录",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string", "default": ""},
                "ref": {"type": "string", "default": "master"}
            },
            "required": ["owner", "repo"]
        },
        handler=handle_gitee_list_contents,
        category="gitee"
    )
    
    MCPToolRegistry.register(
        name="gitee_read_file",
        description="读取 Gitee 文件内容",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string"},
                "ref": {"type": "string", "default": "master"}
            },
            "required": ["owner", "repo", "path"]
        },
        handler=handle_gitee_read_file,
        category="gitee"
    )
    
    MCPToolRegistry.register(
        name="gitee_list_issues",
        description="列出 Gitee Issue",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "state": {"type": "string", "enum": ["open", "closed", "all"]},
                "per_page": {"type": "integer", "default": 10}
            },
            "required": ["owner", "repo"]
        },
        handler=handle_gitee_list_issues,
        category="gitee"
    )
    
    MCPToolRegistry.register(
        name="gitee_search_repos",
        description="搜索 Gitee 仓库",
        input_schema={
            "type": "object",
            "properties": {
                "keyword": {"type": "string"},
                "per_page": {"type": "integer", "default": 5}
            },
            "required": ["keyword"]
        },
        handler=handle_gitee_search_repos,
        category="gitee"
    )
    
    print("[Gitee MCP] Registered 6 Gitee tools")
