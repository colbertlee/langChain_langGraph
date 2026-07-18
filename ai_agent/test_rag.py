import os
from agent import AIAgent

def test_rag():
    print("=" * 60)
    print("RAG 功能测试")
    print("=" * 60)
    
    agent = AIAgent()
    
    kb_path = os.path.join("knowledge_base", "python_intro.txt")
    
    print("\n[测试 1] 加载知识库")
    print("-" * 40)
    result = agent.run(f"加载文档 {kb_path}")
    print(f"输入: 加载文档 {kb_path}")
    print(f"输出: {result}")
    loaded = "成功" in result or "成功" in result
    print(f"状态: {'✅ 成功' if loaded else '❌ 失败'}")
    
    print("\n[测试 2] 查询知识库 - Python 特点")
    print("-" * 40)
    result = agent.run("Python 有哪些特点？")
    print(f"输入: Python 有哪些特点？")
    print(f"输出: {result}")
    has_features = any(feature in result for feature in ["简单", "面向对象", "动态类型", "跨平台"])
    print(f"状态: {'✅ 成功' if has_features else '❌ 失败'}")
    
    print("\n[测试 3] 查询知识库 - Python 应用领域")
    print("-" * 40)
    result = agent.run("Python 可以用于哪些领域？")
    print(f"输入: Python 可以用于哪些领域？")
    print(f"输出: {result}")
    has_domains = any(domain in result for domain in ["Web", "数据", "AI", "游戏"])
    print(f"状态: {'✅ 成功' if has_domains else '❌ 失败'}")
    
    print("\n[测试 4] 查询知识库 - Python 数据类型")
    print("-" * 40)
    result = agent.run("Python 有哪些数据类型？")
    print(f"输入: Python 有哪些数据类型？")
    print(f"输出: {result}")
    has_types = any(t in result for t in ["int", "float", "list", "dict", "str"])
    print(f"状态: {'✅ 成功' if has_types else '❌ 失败'}")
    
    print("\n[测试 5] 未加载知识库时查询")
    print("-" * 40)
    agent2 = AIAgent()
    result = agent2.run("Python 是什么？")
    print(f"输入: Python 是什么？")
    print(f"输出: {result}")
    not_loaded = "未初始化" in result or "加载" in result
    print(f"状态: {'✅ 正确提示未加载' if not_loaded else '❌ 异常'}")
    
    print("\n" + "=" * 60)
    print("RAG 测试完成！")
    print("=" * 60)

if __name__ == "__main__":
    test_rag()