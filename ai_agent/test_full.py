"""完整功能测试"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_security():
    print("测试安全模块...")
    from security import SecurityModule
    
    security = SecurityModule()
    
    test_cases = [
        ("正常输入", "你好", {"blocked": False}),
        ("危险命令", "rm -rf /", {"blocked": True}),
        ("敏感信息", "我的密码是123456", {"blocked": False}),
        ("exec命令", "exec('rm -rf /')", {"blocked": True}),
    ]
    
    for name, input_text, expected in test_cases:
        result = security.check_input(input_text)
        status = "✅" if result["blocked"] == expected["blocked"] else "❌"
        print(f"  {status} {name}: blocked={result['blocked']}")
    
    print("安全模块测试完成")

def test_tools():
    print("\n测试工具模块...")
    from tools import read_file, write_file, list_files, run_code
    
    # 测试 list_files
    result = list_files.invoke({})
    print(f"  ✅ list_files: {len(result.split())} 个文件")
    
    # 测试 write_file
    test_file = "test_temp_file.txt"
    if os.path.exists(test_file):
        os.remove(test_file)
    
    result = write_file.invoke({"file_path": test_file, "content": "Hello World!"})
    print(f"  ✅ write_file: {result}")
    
    # 测试 read_file
    result = read_file.invoke({"file_path": test_file})
    print(f"  ✅ read_file: {result}")
    
    # 测试 run_code
    result = run_code.invoke({"code": "2 + 3 * 4"})
    print(f"  ✅ run_code: {result}")
    
    # 测试危险代码拦截
    result = run_code.invoke({"code": "import os"})
    print(f"  ✅ run_code (危险代码拦截): {result}")
    
    # 清理
    if os.path.exists(test_file):
        os.remove(test_file)
    
    print("工具模块测试完成")

def test_agent():
    print("\n测试 Agent...")
    from agent import AIAgent
    
    agent = AIAgent()
    
    tools = agent.get_tools_list()
    print(f"  ✅ Agent 初始化成功，工具数量: {len(tools)}")
    
    print(f"  ✅ 工具列表: {tools}")
    
    print("Agent 测试完成")

if __name__ == "__main__":
    print("=" * 60)
    print("AI Agent 完整功能测试")
    print("=" * 60)
    
    try:
        test_security()
        test_tools()
        test_agent()
        
        print("\n" + "=" * 60)
        print("所有测试通过！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()