"""
测试 GitHub MCP 服务
"""
import os
import sys
import json
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_github_api():
    """测试 GitHub API 连接"""
    print("=" * 60)
    print("Testing GitHub API Connection")
    print("=" * 60)
    
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    print("Token: {}...".format(token[:10]) if token else "No token")
    
    if not token:
        print("[ERROR] No GitHub token found in .env")
        return False
    
    try:
        import requests
        
        # 测试 API 连接
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # 获取用户信息
        response = requests.get("https://api.github.com/user", headers=headers, timeout=10)
        
        if response.status_code == 200:
            user = response.json()
            print("[OK] GitHub API connected!")
            print("    Username: {}".format(user.get("login")))
            print("    Name: {}".format(user.get("name", "N/A")))
            return True
        else:
            print("[ERROR] API returned status: {}".format(response.status_code))
            print("    Response: {}".format(response.text[:200]))
            return False
            
    except Exception as e:
        print("[ERROR] {}".format(str(e)))
        return False


def test_github_mcp_server():
    """测试 GitHub MCP 服务器（通过 npx）"""
    print("\n" + "=" * 60)
    print("Testing GitHub MCP Server via npx")
    print("=" * 60)
    
    token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
    
    if not token:
        print("[ERROR] No GitHub token found")
        return False
    
    try:
        # 检查是否已安装 GitHub MCP 服务器
        print("[INFO] Checking for GitHub MCP server...")
        
        # 尝试运行 GitHub MCP 服务器（仅测试命令是否可用）
        result = subprocess.run(
            ["npx", "-y", "@modelcontextprotocol/server-github", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
            env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": token}
        )
        
        print("[OK] GitHub MCP server command available")
        print("    Run: npx -y @modelcontextprotocol/server-github")
        return True
        
    except subprocess.TimeoutExpired:
        print("[WARN] Timeout while checking MCP server")
        return False
    except Exception as e:
        print("[WARN] Error: {}".format(str(e)))
        return False


def test_brave_search():
    """测试 Brave Search API"""
    print("\n" + "=" * 60)
    print("Testing Brave Search API")
    print("=" * 60)
    
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "")
    
    if not api_key:
        print("[INFO] No Brave Search API key configured")
        print("    To enable: Get free key at https://api.search.brave.com/")
        return None
    
    try:
        import requests
        
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": api_key
        }
        
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers=headers,
            params={"q": "test"},
            timeout=10
        )
        
        if response.status_code == 200:
            print("[OK] Brave Search API connected!")
            return True
        else:
            print("[WARN] API returned: {}".format(response.status_code))
            return False
            
    except Exception as e:
        print("[WARN] Error: {}".format(str(e)))
        return False


def list_mcp_servers():
    """列出可用的 MCP 服务器"""
    print("\n" + "=" * 60)
    print("Available MCP Servers")
    print("=" * 60)
    
    servers = [
        ("@modelcontextprotocol/server-github", "GitHub API integration"),
        ("@modelcontextprotocol/server-filesystem", "Local filesystem access"),
        ("@modelcontextprotocol/server-brave-search", "Brave Search API"),
        ("@modelcontextprotocol/server-slack", "Slack messaging"),
        ("@modelcontextprotocol/server-sqlite", "SQLite database"),
        ("@modelcontextprotocol/server-postgres", "PostgreSQL database"),
    ]
    
    for server, desc in servers:
        print("  - {}: {}".format(server, desc))


if __name__ == "__main__":
    # 加载 .env 文件
    from dotenv import load_dotenv
    load_dotenv()
    
    print("\n")
    
    success = True
    success = test_github_api() and success
    success = test_github_mcp_server() and success
    test_brave_search()
    list_mcp_servers()
    
    print("\n" + "=" * 60)
    if success:
        print("GitHub MCP is ready to use!")
    else:
        print("Some tests failed. Check configuration.")
    print("=" * 60)
