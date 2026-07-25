from tools import get_current_time, calculate, get_all_tools

def test_tools():
    print("测试工具模块")
    print("=" * 30)
    
    print("测试 get_current_time:")
    result = get_current_time.invoke({})
    print(f"结果: {result}\n")
    
    print("测试 calculate:")
    result = calculate.invoke({"expression": "2 + 3 * 4"})
    print(f"结果: {result}\n")
    
    print("测试 get_all_tools:")
    tools = get_all_tools()
    print(f"工具列表: {[t.name for t in tools]}")

if __name__ == "__main__":
    test_tools()