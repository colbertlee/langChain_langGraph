"""测试 Gitee MCP 工具"""
import os
from dotenv import load_dotenv

load_dotenv()

print("=" * 50)
print("Testing Gitee MCP Tools")
print("=" * 50)

# 测试搜索仓库
print("\n1. Test: gitee_search_repos")
from gitee_tools import handle_gitee_search_repos
result = handle_gitee_search_repos({"keyword": "fastapi", "per_page": 3})
print(result[:500])

print("\n" + "=" * 50)
print("All tests completed!")
print("=" * 50)
