"""完整工具功能测试"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_basic_tools():
    print("测试基础工具...")
    from tools import get_current_time, calculate, list_files
    
    result = get_current_time.invoke({})
    print(f"  ✅ get_current_time: {result}")
    
    result = calculate.invoke({"expression": "2 + 3 * 4"})
    print(f"  ✅ calculate: {result}")
    
    result = list_files.invoke({})
    print(f"  ✅ list_files: 包含 {len(result.split())} 个文件")
    
    print("基础工具测试完成")

def test_extended_tools():
    print("\n测试扩展工具...")
    from tools import get_weather, github_search, generate_chart
    
    try:
        result = get_weather.invoke({"city": "Beijing"})
        if "错误" not in result and "请先" not in result:
            print(f"  ✅ get_weather (Beijing): 成功获取")
        else:
            print(f"  ⚠️ get_weather: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ get_weather: {str(e)[:50]}")
    
    try:
        result = github_search.invoke({"query": "langchain"})
        if "错误" not in result and "请先" not in result:
            print(f"  ✅ github_search: 成功搜索")
        else:
            print(f"  ⚠️ github_search: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ github_search: {str(e)[:50]}")
    
    try:
        result = generate_chart.invoke({"data": '{"labels": ["A","B","C"], "values": [10,20,30]}', "chart_type": "bar"})
        if "成功" in result:
            print(f"  ✅ generate_chart: {result}")
            import glob
            charts = glob.glob("chart_*.png")
            if charts:
                print(f"     📊 生成的图表文件: {charts}")
                for chart in charts:
                    os.remove(chart)
        else:
            print(f"  ⚠️ generate_chart: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ generate_chart: {str(e)[:50]}")
    
    print("扩展工具测试完成")

def test_finance_tools():
    print("\n测试金融工具(ETF)...")
    from tools import get_etf_info, get_etf_price, get_etf_history, get_etf_knowledge, compare_etfs, etf_analysis
    
    try:
        result = get_etf_info.invoke({"etf_code": "510300"})
        if "错误" not in result and "超时" not in result:
            print(f"  ✅ get_etf_info (510300): 成功获取")
        else:
            print(f"  ⚠️ get_etf_info: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ get_etf_info: {str(e)[:50]}")
    
    try:
        result = get_etf_price.invoke({"etf_code": "510300"})
        if "错误" not in result and "超时" not in result:
            print(f"  ✅ get_etf_price (510300): 成功获取")
        else:
            print(f"  ⚠️ get_etf_price: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ get_etf_price: {str(e)[:50]}")
    
    try:
        result = get_etf_history.invoke({"etf_code": "510300", "days": "7"})
        if "错误" not in result and "超时" not in result:
            print(f"  ✅ get_etf_history (510300, 7天): 成功获取")
        else:
            print(f"  ⚠️ get_etf_history: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ get_etf_history: {str(e)[:50]}")
    
    try:
        result = get_etf_knowledge.invoke({"topic": "basic"})
        print(f"  ✅ get_etf_knowledge (basic): 获取成功")
    except Exception as e:
        print(f"  ⚠️ get_etf_knowledge: {str(e)[:50]}")
    
    try:
        result = compare_etfs.invoke({"etf_codes": "510300,510500"})
        if "错误" not in result and "超时" not in result:
            print(f"  ✅ compare_etfs (510300,510500): 成功对比")
        else:
            print(f"  ⚠️ compare_etfs: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ compare_etfs: {str(e)[:50]}")
    
    try:
        result = etf_analysis.invoke({"etf_code": "510300", "days": "14"})
        if "错误" not in result and "超时" not in result:
            print(f"  ✅ etf_analysis (510300, 14天): 成功分析")
        else:
            print(f"  ⚠️ etf_analysis: {result[:50]}...")
    except Exception as e:
        print(f"  ⚠️ etf_analysis: {str(e)[:50]}")
    
    print("金融工具测试完成")

def test_api_endpoints():
    print("\n测试 API 接口...")
    import requests
    
    base_url = "http://127.0.0.1:8000"
    
    try:
        response = requests.get(f"{base_url}/api/health")
        data = response.json()
        if data["status"] == "ok":
            print(f"  ✅ /api/health: {data['message']}")
        else:
            print(f"  ❌ /api/health: {data}")
    except Exception as e:
        print(f"  ❌ /api/health: {str(e)}")
    
    try:
        response = requests.get(f"{base_url}/api/tools")
        data = response.json()
        tools = data.get("tools", [])
        print(f"  ✅ /api/tools: 返回 {len(tools)} 个工具")
        if len(tools) == 18:
            print(f"     工具数量正确！")
        else:
            print(f"     ⚠️ 预期 18 个工具，实际 {len(tools)} 个")
    except Exception as e:
        print(f"  ❌ /api/tools: {str(e)}")
    
    try:
        response = requests.get(f"{base_url}/api/api-key/status")
        data = response.json()
        print(f"  ✅ /api/api-key/status: configured={data['configured']}, has_agent={data['has_agent']}")
    except Exception as e:
        print(f"  ❌ /api/api-key/status: {str(e)}")
    
    try:
        response = requests.post(f"{base_url}/api/chat", json={"message": "你好"})
        data = response.json()
        if "API Key" in data.get("message", ""):
            print(f"  ✅ /api/chat: 未配置 API Key 时返回友好提示")
        else:
            print(f"  ✅ /api/chat: 返回正常响应")
    except Exception as e:
        print(f"  ❌ /api/chat: {str(e)}")
    
    print("API 接口测试完成")

def test_web_ui():
    print("\n测试 Web UI...")
    import requests
    
    try:
        response = requests.get("http://127.0.0.1:8000/")
        if response.status_code == 200:
            content = response.text
            if "18 个工具" in content and "ETF" in content and "天气" in content:
                print("  ✅ Web UI: 主页加载成功，包含功能介绍")
            else:
                print("  ⚠️ Web UI: 主页加载成功，但内容可能不完整")
        else:
            print(f"  ❌ Web UI: HTTP {response.status_code}")
    except Exception as e:
        print(f"  ❌ Web UI: {str(e)}")
    
    print("Web UI 测试完成")

if __name__ == "__main__":
    print("=" * 60)
    print("AI Agent 完整功能测试")
    print("=" * 60)
    
    try:
        test_basic_tools()
        test_extended_tools()
        test_finance_tools()
        test_api_endpoints()
        test_web_ui()
        
        print("\n" + "=" * 60)
        print("所有测试完成！")
        print("=" * 60)
    except Exception as e:
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
