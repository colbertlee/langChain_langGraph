"""
MCP 服务管理器
启动和管理外部 MCP 服务器（GitHub, Brave Search 等）
"""
import os
import sys
import json
import subprocess
import signal
from datetime import datetime

class MCPServerManager:
    """MCP 服务器管理器"""
    
    def __init__(self):
        self.servers = {}
        self.processes = {}
        self.load_config()
    
    def load_config(self):
        """加载 MCP 配置"""
        config_path = os.path.join(os.path.dirname(__file__), "mcp_config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            self.config = {"external_servers": {}}
    
    def start_github_server(self) -> bool:
        """启动 GitHub MCP 服务器"""
        token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
        
        if not token:
            print("[ERROR] GitHub token not found in .env")
            return False
        
        github_config = self.config.get("external_servers", {}).get("github", {})
        if not github_config.get("enabled", False):
            print("[INFO] GitHub MCP server is disabled in mcp_config.json")
            return False
        
        try:
            cmd = github_config.get("command", "npx")
            args = github_config.get("args", ["-y", "@modelcontextprotocol/server-github"])
            
            env = os.environ.copy()
            env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
            
            print("[INFO] Starting GitHub MCP server...")
            print("[INFO] Command: {} {}".format(cmd, " ".join(args)))
            
            process = subprocess.Popen(
                [cmd] + args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.processes["github"] = process
            print("[OK] GitHub MCP server started (PID: {})".format(process.pid))
            return True
            
        except Exception as e:
            print("[ERROR] Failed to start GitHub MCP server: {}".format(str(e)))
            return False
    
    def start_brave_search_server(self) -> bool:
        """启动 Brave Search MCP 服务器"""
        api_key = os.getenv("BRAVE_SEARCH_API_KEY", "")
        
        if not api_key:
            print("[WARN] Brave Search API key not found")
            return False
        
        brave_config = self.config.get("external_servers", {}).get("brave-search", {})
        if not brave_config.get("enabled", False):
            print("[INFO] Brave Search MCP server is disabled")
            return False
        
        try:
            cmd = brave_config.get("command", "npx")
            args = brave_config.get("args", ["-y", "@modelcontextprotocol/server-brave-search"])
            
            env = os.environ.copy()
            env["BRAVE_SEARCH_API_KEY"] = api_key
            
            print("[INFO] Starting Brave Search MCP server...")
            
            process = subprocess.Popen(
                [cmd] + args,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            self.processes["brave-search"] = process
            print("[OK] Brave Search MCP server started (PID: {})".format(process.pid))
            return True
            
        except Exception as e:
            print("[ERROR] Failed to start Brave Search MCP server: {}".format(str(e)))
            return False
    
    def start_all(self):
        """启动所有启用的 MCP 服务器"""
        print("=" * 60)
        print("MCP Server Manager")
        print("=" * 60)
        print("Time: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        print()
        
        # 加载 .env
        from dotenv import load_dotenv
        load_dotenv()
        
        # GitHub
        if self.config.get("external_servers", {}).get("github", {}).get("enabled", False):
            self.start_github_server()
        else:
            print("[INFO] GitHub MCP: disabled")
        
        # Brave Search
        if self.config.get("external_servers", {}).get("brave-search", {}).get("enabled", False):
            self.start_brave_search_server()
        else:
            print("[INFO] Brave Search MCP: disabled")
        
        print()
        print("=" * 60)
        print("Use Ctrl+C to stop all servers")
        print("=" * 60)
        
        # 等待信号
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[INFO] Stopping MCP servers...")
            self.stop_all()
    
    def stop_all(self):
        """停止所有 MCP 服务器"""
        for name, process in self.processes.items():
            try:
                process.terminate()
                process.wait(timeout=5)
                print("[OK] Stopped {}".format(name))
            except:
                try:
                    process.kill()
                    print("[OK] Killed {}".format(name))
                except:
                    print("[WARN] Could not stop {}".format(name))


def main():
    """主函数"""
    if len(sys.argv) > 1:
        command = sys.argv[1].lower()
        
        manager = MCPServerManager()
        
        if command == "start":
            manager.start_all()
        elif command == "github":
            manager.start_github_server()
        elif command == "brave":
            manager.start_brave_search_server()
        elif command == "list":
            list_servers()
        else:
            print("Usage: python start_mcp.py [start|github|brave|list]")
    else:
        # 交互模式
        manager = MCPServerManager()
        
        print("MCP Server Manager")
        print("=" * 40)
        print("1. Start all enabled servers")
        print("2. Start GitHub server")
        print("3. Start Brave Search server")
        print("4. List available servers")
        print("0. Exit")
        print()
        
        choice = input("Select option: ").strip()
        
        if choice == "1":
            manager.start_all()
        elif choice == "2":
            manager.start_github_server()
        elif choice == "3":
            manager.start_brave_search_server()
        elif choice == "4":
            list_servers()


def list_servers():
    """列出可用服务器"""
    print("\nAvailable MCP Servers:")
    print("-" * 40)
    
    servers = [
        ("github", "GitHub API", "@modelcontextprotocol/server-github"),
        ("brave-search", "Brave Search", "@modelcontextprotocol/server-brave-search"),
        ("filesystem", "Local Files", "@modelcontextprotocol/server-filesystem"),
        ("slack", "Slack", "@modelcontextprotocol/server-slack"),
        ("sqlite", "SQLite", "@modelcontextprotocol/server-sqlite"),
        ("postgres", "PostgreSQL", "@modelcontextprotocol/server-postgres"),
    ]
    
    for name, desc, pkg in servers:
        print("  {}: {} ({})".format(name, desc, pkg))
    
    print()


if __name__ == "__main__":
    main()
