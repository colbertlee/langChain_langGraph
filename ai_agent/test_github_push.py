"""测试 GitHub Push 操作"""
import requests
import base64
import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")
REPO = "colbertlee/ai-agent-test"

def test_push_file():
    """测试创建新文件"""
    url = f"https://api.github.com/repos/{REPO}/contents/agent_capabilities.md"
    headers = {
        "Authorization": f"token {TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    
    # 文件内容
    content = """# AI Agent 功能清单

## 核心能力

- 多轮对话记忆（SQLite 持久化）
- 18+ LangChain 工具
- 14 MCP 工具
- 5 Skill 技能

## 工具分类

### LangChain 工具
- get_current_time, calculate, search_web
- query/load_knowledge_base
- read/write_file, list_files, run_code

### MCP 工具
- file: 文件操作
- web: HTTP 请求
- development: Git、 Docker
- system: 系统信息
- data: JSON 处理

### Skill 技能
- deep_research: 深度研究
- code_documentation: 代码文档
- ppt_generation: PPT 生成
- paper_review: 论文审阅
- chart_visualization: 图表可视化

## 技术栈

- LangChain + LangGraph
- FastAPI + WebSocket
- Chroma 向量数据库
- SQLite 持久化
"""
    
    data = {
        "message": "Add agent_capabilities.md via API",
        "content": base64.b64encode(content.encode()).decode()
    }
    
    print(f"URL: {url}")
    print(f"Content length: {len(content)} bytes")
    
    r = requests.put(url, headers=headers, json=data)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:500]}")
    
    if r.status_code in [201, 200]:
        print("\n✅ Push 成功！")
        result = r.json()
        print(f"文件: {result.get('content', {}).get('path')}")
        print(f"URL: {result.get('content', {}).get('html_url')}")
    else:
        print(f"\n❌ Push 失败: {r.status_code}")

if __name__ == "__main__":
    test_push_file()
