from agent import AIAgent

def test_agent():
    agent = AIAgent()
    
    print("测试 1: 获取当前时间")
    result = agent.run("现在几点了？")
    print(f"AI: {result}\n")
    
    print("测试 2: 数学计算")
    result = agent.run("计算 2 + 3 * 4")
    print(f"AI: {result}\n")
    
    print("测试 3: 多轮对话")
    result = agent.run("我叫张三")
    print(f"AI: {result}\n")
    
    result = agent.run("你还记得我叫什么吗？")
    print(f"AI: {result}\n")

if __name__ == "__main__":
    test_agent()