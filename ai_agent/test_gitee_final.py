"""测试 Gitee API"""
import sys
import io

# 设置 UTF-8 输出
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from gitee_tools import handle_gitee_list_repos

result = handle_gitee_list_repos({})
print(result)
