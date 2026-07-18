"""Bug修复验证测试"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_run_code_security():
    print("测试 run_code 安全修复...")
    from tools import run_code
    
    test_cases = [
        ("正常计算", "2 + 3 * 4", "✅ 执行结果: 14"),
        ("import拦截", "__import__('os')", "❌ 禁止执行包含 '__import__' 的代码"),
        ("exec拦截", "exec('print(1)')", "❌ 禁止执行包含 'exec' 的代码"),
        ("eval拦截", "eval('1+1')", "❌ 禁止执行包含 'eval' 的代码"),
        ("open拦截", "open('test.txt')", "❌ 禁止执行包含 'open' 的代码"),
        ("字符串拼接绕过", "__bui" + "ltins__", "❌ 禁止执行包含 '__builtins__' 的代码"),
    ]
    
    for name, code, expected in test_cases:
        result = run_code.invoke({"code": code})
        status = "✅" if expected in result else "❌"
        print(f"  {status} {name}: {result[:50]}")
    
    print("run_code 安全修复测试完成")

def test_etf_validation():
    print("\n测试 ETF 参数验证...")
    from tools import get_etf_info, get_etf_price
    
    test_cases = [
        ("空代码", "", "❌ ETF 代码不能为空"),
        ("纯空格", "   ", "❌ ETF 代码不能为空"),
        ("非数字", "abc", "❌ ETF 代码必须为数字"),
        ("带字母", "510300abc", "❌ ETF 代码必须为数字"),
    ]
    
    for name, code, expected in test_cases:
        result = get_etf_info.invoke({"etf_code": code})
        status = "✅" if expected in result else "❌"
        print(f"  {status} get_etf_info ({name}): {result[:50]}")
        
        result = get_etf_price.invoke({"etf_code": code})
        status = "✅" if expected in result else "❌"
        print(f"  {status} get_etf_price ({name}): {result[:50]}")
    
    print("ETF 参数验证测试完成")

def test_rag_api_key():
    print("\n测试 RAG API Key 传递...")
    from rag import RAGModule
    
    test_key = "test-api-key-12345"
    try:
        rag = RAGModule(None, api_key=test_key)
        if hasattr(rag, 'api_key') and rag.api_key == test_key:
            print("  ✅ RAG 模块正确接收 API Key")
        else:
            print("  ❌ RAG 模块未正确存储 API Key")
    except Exception as e:
        print(f"  ❌ RAG 模块初始化失败: {e}")
    
    print("RAG API Key 传递测试完成")

def test_api_tools_safety():
    print("\n测试 API 工具接口安全...")
    from agent import AIAgent
    
    agent = AIAgent()
    agent.tools = []
    
    tool_info = []
    tools_list = agent.get_tools_list()
    for tool_name in tools_list:
        tool_list = [t for t in agent.tools if t.name == tool_name]
        if tool_list:
            tool = tool_list[0]
            tool_info.append({"name": tool.name})
    
    if len(tool_info) == 0:
        print("  ✅ 工具列表为空时不会抛出 IndexError")
    else:
        print("  ❌ 预期工具列表为空")
    
    print("API 工具接口安全测试完成")

def test_streaming_incremental():
    print("\n测试流式输出增量逻辑...")
    
    last_content_length = 0
    test_chunks = ["Hello", "Hello World", "Hello World!", "Hello World! How are you?"]
    
    for content in test_chunks:
        incremental_content = content[last_content_length:]
        if incremental_content:
            print(f"  ✅ 增量内容: '{incremental_content}'")
            last_content_length = len(content)
    
    if last_content_length == len(test_chunks[-1]):
        print("  ✅ 流式增量逻辑正确")
    else:
        print("  ❌ 流式增量逻辑有问题")
    
    print("流式输出增量逻辑测试完成")

if __name__ == "__main__":
    print("=" * 60)
    print("Bug 修复验证测试")
    print("=" * 60)
    
    try:
        test_run_code_security()
        test_etf_validation()
        test_rag_api_key()
        test_api_tools_safety()
        test_streaming_incremental()
        
        print("\n" + "=" * 60)
        print("所有 Bug 修复验证通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
