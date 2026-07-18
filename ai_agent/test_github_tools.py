"""测试 GitHub MCP 工具"""
import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
load_dotenv()

print("=" * 50)
print("Testing GitHub MCP Tools")
print("=" * 50)

# 测试列表仓库
print("\n1. Test: github_list_repos")
from github_tools import handle_github_list_repos
result = handle_github_list_repos({"username": "colbertlee", "per_page": 3})
print(result[:500])

# 测试搜索仓库
print("\n\n2. Test: github_search_repos")
from github_tools import handle_github_search_repos
result = handle_github_search_repos({"query": "langchain", "per_page": 3})
print(result[:500])

print("\n" + "=" * 50)
print("All tests completed!")
print("=" * 50)
