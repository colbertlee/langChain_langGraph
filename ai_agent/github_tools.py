"""
GitHub MCP 工具集

提供 GitHub API 操作能力：仓库、文件、Issue、PR 等
"""
import os
import base64
import json
from typing import Any, Dict, List, Optional
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

# GitHub Token
GITHUB_TOKEN = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
GITHUB_API_BASE = "https://api.github.com"

def get_headers() -> Dict[str, str]:
    """获取请求头"""
    headers = {
        "Accept": "application/vnd.github.v3+json"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


# ==================== 仓库操作 ====================

def handle_github_list_repos(args: Dict[str, Any]) -> str:
    """列出用户仓库"""
    username = args.get("username", "")
    visibility = args.get("visibility", "all")  # all/public/private
    sort_by = args.get("sort", "updated")  # updated/created/push/full_name
    per_page = args.get("per_page", 10)
    
    try:
        if username:
            url = f"{GITHUB_API_BASE}/users/{username}/repos"
        else:
            url = f"{GITHUB_API_BASE}/user/repos"
        
        params = {
            "sort": sort_by,
            "per_page": per_page,
            "visibility": visibility
        }
        
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        repos = response.json()
        
        if not isinstance(repos, list):
            return f"Error: {repos.get('message', 'Failed to fetch repos')}"
        
        result = f"Repositories ({visibility}):\n"
        result += "=" * 50 + "\n"
        
        for repo in repos:
            name = repo.get("full_name", "N/A")
            desc = repo.get("description", "N/A")
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language", "N/A")
            result += f"\n{name}\n"
            result += f"  Stars: {stars} | Lang: {lang}\n"
            result += f"  {desc}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_github_get_repo(args: Dict[str, Any]) -> str:
    """获取仓库详情"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    
    if not owner or not repo:
        return "Error: owner and repo are required"
    
    try:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
        response = requests.get(url, headers=get_headers(), timeout=10)
        data = response.json()
        
        if "message" in data:
            return f"Error: {data['message']}"
        
        result = f"Repository: {data['full_name']}\n"
        result += "=" * 50 + "\n"
        result += f"Description: {data.get('description', 'N/A')}\n"
        result += f"Stars: {data.get('stargazers_count', 0)}\n"
        result += f"Forks: {data.get('forks_count', 0)}\n"
        result += f"Language: {data.get('language', 'N/A')}\n"
        result += f"Default Branch: {data.get('default_branch', 'main')}\n"
        result += f"Open Issues: {data.get('open_issues_count', 0)}\n"
        result += f"Created: {data.get('created_at', 'N/A')[:10]}\n"
        result += f"Updated: {data.get('pushed_at', 'N/A')[:10]}\n"
        result += f"URL: {data.get('html_url', 'N/A')}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== 文件操作 ====================

def handle_github_list_contents(args: Dict[str, Any]) -> str:
    """列出仓库内容"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    path = args.get("path", "")
    ref = args.get("ref", "main")
    
    if not owner or not repo:
        return "Error: owner and repo are required"
    
    try:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        params = {"ref": ref} if ref else {}
        
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        contents = response.json()
        
        if isinstance(contents, dict) and "message" in contents:
            return f"Error: {contents['message']}"
        
        if not isinstance(contents, list):
            return f"Error: Path is a file, not a directory"
        
        result = f"Contents of {owner}/{repo}/{path or '.'} (ref: {ref}):\n"
        result += "=" * 50 + "\n"
        
        for item in contents:
            item_type = item.get("type", "file")
            name = item.get("name", "N/A")
            size = item.get("size", 0)
            if item_type == "dir":
                result += f"[DIR]  {name}/\n"
            else:
                result += f"[FILE] {name} ({size} bytes)\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_github_read_file(args: Dict[str, Any]) -> str:
    """读取文件内容"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    path = args.get("path", "")
    ref = args.get("ref", "main")
    
    if not owner or not repo or not path:
        return "Error: owner, repo, and path are required"
    
    try:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        params = {"ref": ref} if ref else {}
        
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        data = response.json()
        
        if "message" in data:
            return f"Error: {data['message']}"
        
        if data.get("type") == "dir":
            return "Error: Path is a directory, not a file"
        
        content = data.get("content", "")
        if content:
            # Base64 解码
            decoded = base64.b64decode(content).decode("utf-8")
            # 限制长度
            if len(decoded) > 5000:
                return decoded[:5000] + f"\n... (truncated, total {len(decoded)} chars)"
            return decoded
        
        return "Error: No content found"
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_github_create_file(args: Dict[str, Any]) -> str:
    """创建或更新文件"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    path = args.get("path", "")
    content = args.get("content", "")
    message = args.get("message", "Update via AI Agent")
    
    if not owner or not repo or not path or not content:
        return "Error: owner, repo, path, and content are required"
    
    try:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
        
        data = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode()
        }
        
        # 检查文件是否存在
        check_response = requests.get(url, headers=get_headers())
        if check_response.status_code == 200:
            # 文件存在，需要更新
            sha = check_response.json().get("sha")
            data["sha"] = sha
        
        response = requests.put(url, headers=get_headers(), json=data, timeout=10)
        
        if response.status_code in [200, 201]:
            result = response.json()
            return f"Success! File created/updated: {result.get('content', {}).get('path')}\nURL: {result.get('content', {}).get('html_url')}"
        else:
            return f"Error: {response.status_code} - {response.text[:200]}"
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== Issue 操作 ====================

def handle_github_list_issues(args: Dict[str, Any]) -> str:
    """列出 Issue"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    state = args.get("state", "open")  # open/closed/all
    labels = args.get("labels", "")
    per_page = args.get("per_page", 10)
    
    if not owner or not repo:
        return "Error: owner and repo are required"
    
    try:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues"
        
        params = {
            "state": state,
            "per_page": per_page,
            "sort": "updated"
        }
        if labels:
            params["labels"] = labels
        
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        issues = response.json()
        
        if isinstance(issues, dict) and "message" in issues:
            return f"Error: {issues['message']}"
        
        result = f"Issues ({state}) in {owner}/{repo}:\n"
        result += "=" * 50 + "\n"
        
        for issue in issues[:per_page]:
            if "pull_request" in issue:
                continue  # 跳过 PR
            
            num = issue.get("number", 0)
            title = issue.get("title", "N/A")
            state_emoji = "[+]" if issue.get("state") == "open" else "[-]"
            result += f"\n#{num} {state_emoji} {title}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_github_create_issue(args: Dict[str, Any]) -> str:
    """创建 Issue"""
    owner = args.get("owner", "")
    repo = args.get("repo", "")
    title = args.get("title", "")
    body = args.get("body", "")
    labels = args.get("labels", [])
    
    if not owner or not repo or not title:
        return "Error: owner, repo, and title are required"
    
    try:
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues"
        
        data = {
            "title": title,
            "body": body or f"Created by AI Agent on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        }
        if labels:
            data["labels"] = labels
        
        response = requests.post(url, headers=get_headers(), json=data, timeout=10)
        result = response.json()
        
        if "message" in result:
            return f"Error: {result['message']}"
        
        return f"Issue created!\n#{result.get('number')}: {result.get('title')}\nURL: {result.get('html_url')}"
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== 搜索操作 ====================

def handle_github_search_repos(args: Dict[str, Any]) -> str:
    """搜索仓库"""
    query = args.get("query", "")
    language = args.get("language", "")
    sort = args.get("sort", "stars")  # stars/forks/updated
    per_page = args.get("per_page", 5)
    
    if not query:
        return "Error: query is required"
    
    try:
        url = f"{GITHUB_API_BASE}/search/repositories"
        
        params = {
            "q": query,
            "sort": sort,
            "per_page": per_page
        }
        if language:
            params["q"] += f" language:{language}"
        
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        data = response.json()
        
        if "message" in data:
            return f"Error: {data['message']}"
        
        repos = data.get("items", [])
        
        result = f"Search results for '{query}':\n"
        result += "=" * 50 + "\n"
        
        for repo in repos:
            name = repo.get("full_name", "N/A")
            stars = repo.get("stargazers_count", 0)
            lang = repo.get("language", "N/A")
            desc = repo.get("description", "N/A")[:60]
            result += f"\n{name}\n"
            result += f"  Stars: {stars} | Lang: {lang}\n"
            result += f"  {desc}...\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


def handle_github_search_code(args: Dict[str, Any]) -> str:
    """搜索代码"""
    query = args.get("query", "")
    repo = args.get("repo", "")  # 限制在某个仓库
    per_page = args.get("per_page", 5)
    
    if not query:
        return "Error: query is required"
    
    try:
        url = f"{GITHUB_API_BASE}/search/code"
        
        params = {
            "q": query,
            "per_page": per_page
        }
        if repo:
            params["q"] += f" repo:{repo}"
        
        response = requests.get(url, headers=get_headers(), params=params, timeout=10)
        data = response.json()
        
        if "message" in data:
            return f"Error: {data['message']}"
        
        items = data.get("items", [])
        
        result = f"Code search results for '{query}':\n"
        result += "=" * 50 + "\n"
        
        for item in items:
            name = item.get("name", "N/A")
            path = item.get("path", "N/A")
            repo = item.get("repository", {}).get("full_name", "N/A")
            result += f"\n{path}\n"
            result += f"  Repository: {repo}\n"
        
        return result
        
    except Exception as e:
        return f"Error: {str(e)}"


# ==================== 注册所有 GitHub MCP 工具 ====================

def register_all_github_tools():
    """注册所有 GitHub MCP 工具"""
    from mcp_tools import MCPToolRegistry
    
    # 仓库操作
    MCPToolRegistry.register(
        name="github_list_repos",
        description="列出 GitHub 用户仓库",
        input_schema={
            "type": "object",
            "properties": {
                "username": {"type": "string", "description": "用户名（空则列出当前用户）"},
                "visibility": {"type": "string", "enum": ["all", "public", "private"]},
                "sort": {"type": "string", "enum": ["updated", "created", "full_name"]},
                "per_page": {"type": "integer", "default": 10}
            }
        },
        handler=handle_github_list_repos,
        category="github"
    )
    
    MCPToolRegistry.register(
        name="github_get_repo",
        description="获取仓库详情",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"}
            },
            "required": ["owner", "repo"]
        },
        handler=handle_github_get_repo,
        category="github"
    )
    
    # 文件操作
    MCPToolRegistry.register(
        name="github_list_contents",
        description="列出仓库目录内容",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string", "default": ""},
                "ref": {"type": "string", "default": "main"}
            },
            "required": ["owner", "repo"]
        },
        handler=handle_github_list_contents,
        category="github"
    )
    
    MCPToolRegistry.register(
        name="github_read_file",
        description="读取仓库文件内容",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string"},
                "ref": {"type": "string", "default": "main"}
            },
            "required": ["owner", "repo", "path"]
        },
        handler=handle_github_read_file,
        category="github"
    )
    
    MCPToolRegistry.register(
        name="github_create_file",
        description="创建或更新仓库文件",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
                "message": {"type": "string", "default": "Update via AI Agent"}
            },
            "required": ["owner", "repo", "path", "content"]
        },
        handler=handle_github_create_file,
        category="github"
    )
    
    # Issue 操作
    MCPToolRegistry.register(
        name="github_list_issues",
        description="列出仓库 Issue",
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
        handler=handle_github_list_issues,
        category="github"
    )
    
    MCPToolRegistry.register(
        name="github_create_issue",
        description="创建 Issue",
        input_schema={
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "repo": {"type": "string"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "labels": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["owner", "repo", "title"]
        },
        handler=handle_github_create_issue,
        category="github"
    )
    
    # 搜索操作
    MCPToolRegistry.register(
        name="github_search_repos",
        description="搜索 GitHub 仓库",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "language": {"type": "string"},
                "sort": {"type": "string", "enum": ["stars", "forks", "updated"]},
                "per_page": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        },
        handler=handle_github_search_repos,
        category="github"
    )
    
    MCPToolRegistry.register(
        name="github_search_code",
        description="搜索仓库代码",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "repo": {"type": "string"},
                "per_page": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        },
        handler=handle_github_search_code,
        category="github"
    )
    
    print("[GitHub MCP] Registered 9 GitHub tools")
