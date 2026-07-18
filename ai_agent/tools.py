from datetime import datetime
import math
import os
from typing import Union
import json

from langchain_core.tools import tool

_rag_instance = None


def set_rag_instance(rag):
    global _rag_instance
    _rag_instance = rag


def get_rag_instance():
    return _rag_instance


@tool
def get_current_time() -> str:
    """获取当前时间和日期"""
    now = datetime.now()
    return now.strftime("%Y-%m-%d %H:%M:%S")


@tool
def calculate(expression: str) -> Union[float, int, str]:
    """
    数学计算工具
    
    参数:
        expression: 数学表达式，支持 +、-、*、/、^、sqrt、sin、cos、tan 等
    """
    try:
        expression = expression.replace("^", "**")
        result = eval(expression, {"__builtins__": None}, {
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "sqrt": math.sqrt,
            "abs": abs,
            "log": math.log,
            "log10": math.log10,
            "exp": math.exp,
            "pi": math.pi,
            "e": math.e,
        })
        return result
    except Exception as e:
        return f"计算错误: {str(e)}"


@tool
def search_web(query: str) -> str:
    """
    网络搜索工具
    
    参数:
        query: 搜索关键词
    """
    try:
        from serpapi import GoogleSearch
        
        from config import SERPAPI_API_KEY
        
        if not SERPAPI_API_KEY:
            return "请先配置 SERPAPI_API_KEY 环境变量"
        
        search = GoogleSearch({
            "q": query,
            "api_key": SERPAPI_API_KEY,
            "num": 5
        })
        
        results = search.get_dict()
        if "organic_results" in results:
            summaries = []
            for result in results["organic_results"][:5]:
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                link = result.get("link", "")
                summaries.append(f"{title}\n{snippet}\n{link}")
            return "\n\n".join(summaries)
        return "未找到相关结果"
    except ImportError:
        return "请安装 serpapi 包: pip install serpapi"
    except Exception as e:
        return f"搜索错误: {str(e)}"


@tool
def query_knowledge_base(query: str) -> str:
    """
    查询知识库文档
    
    参数:
        query: 查询问题
    """
    rag = get_rag_instance()
    if not rag:
        return "知识库未初始化，请先加载文档"
    
    return rag.query(query)


@tool
def load_knowledge_base(file_path: str) -> str:
    """
    加载文档到知识库
    
    参数:
        file_path: 文档文件路径（txt格式）
    """
    rag = get_rag_instance()
    if not rag:
        return "知识库未初始化"
    
    if not os.path.exists(file_path):
        return f"文件不存在: {file_path}"
    
    try:
        success = rag.load_documents([file_path])
        return "文档加载成功" if success else "文档加载失败"
    except Exception as e:
        return f"加载失败: {str(e)}"


@tool
def read_file(file_path: str) -> str:
    """
    读取文件内容
    
    参数:
        file_path: 文件路径（相对路径，不允许访问上级目录）
    """
    if ".." in file_path or file_path.startswith("/"):
        return "❌ 不允许访问上级目录或绝对路径"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            if len(content) > 5000:
                return content[:5000] + "\n...（文件过长，只显示前5000字符）"
            return content
    except FileNotFoundError:
        return f"❌ 文件不存在: {file_path}"
    except PermissionError:
        return f"❌ 没有权限读取文件: {file_path}"
    except Exception as e:
        return f"❌ 读取错误: {str(e)}"


@tool
def write_file(file_path: str, content: str, append: bool = False) -> str:
    """
    写入文件内容
    
    参数:
        file_path: 文件路径（相对路径，不允许访问上级目录）
        content: 要写入的内容
        append: 是否追加写入（默认False）
    """
    if ".." in file_path or file_path.startswith("/"):
        return "❌ 不允许访问上级目录或绝对路径"
    
    try:
        mode = 'a' if append else 'w'
        with open(file_path, mode, encoding='utf-8') as f:
            f.write(content)
        action = "追加" if append else "写入"
        return f"✅ 文件 {file_path} {action}成功"
    except PermissionError:
        return f"❌ 没有权限写入文件: {file_path}"
    except Exception as e:
        return f"❌ 写入错误: {str(e)}"


@tool
def list_files(directory: str = ".") -> str:
    """
    列出目录下的文件
    
    参数:
        directory: 目录路径（默认当前目录）
    """
    if ".." in directory or directory.startswith("/"):
        return "❌ 不允许访问上级目录或绝对路径"
    
    try:
        files = os.listdir(directory)
        if not files:
            return "目录为空"
        return "\n".join(files)
    except FileNotFoundError:
        return f"❌ 目录不存在: {directory}"
    except PermissionError:
        return f"❌ 没有权限访问目录: {directory}"
    except Exception as e:
        return f"❌ 列出文件错误: {str(e)}"


@tool
def run_code(code: str) -> str:
    """
    执行简单的 Python 代码（仅安全表达式）
    
    参数:
        code: Python 表达式（不允许 import、exec、eval、os、subprocess 等危险操作）
    """
    import ast
    
    dangerous_patterns = ['import', 'exec', 'eval', 'open', '__import__', '__builtins__']
    
    for pattern in dangerous_patterns:
        if pattern in code:
            return f"❌ 禁止执行包含 '{pattern}' 的代码"
    
    try:
        tree = ast.parse(code, mode='eval')
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom):
                return "❌ 禁止执行 import 语句"
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    if node.func.id in ['exec', 'eval', 'open', '__import__']:
                        return f"❌ 禁止调用 '{node.func.id}' 函数"
                elif isinstance(node.func, ast.Attribute):
                    attr_chain = []
                    current = node.func
                    while isinstance(current, ast.Attribute):
                        attr_chain.insert(0, current.attr)
                        current = current.value
                    if isinstance(current, ast.Name):
                        attr_chain.insert(0, current.id)
                    full_name = '.'.join(attr_chain)
                    if full_name in ['os.system', 'os.popen', 'subprocess.call', 
                                     'subprocess.run', 'subprocess.Popen']:
                        return f"❌ 禁止调用 '{full_name}'"
        
        result = eval(code, {"__builtins__": None}, {
            "sin": math.sin,
            "cos": math.cos,
            "tan": math.tan,
            "sqrt": math.sqrt,
            "abs": abs,
            "log": math.log,
            "log10": math.log10,
            "exp": math.exp,
            "pi": math.pi,
            "e": math.e,
            "sum": sum,
            "max": max,
            "min": min,
            "pow": pow,
            "round": round,
            "len": len,
            "range": range,
        })
        return f"✅ 执行结果: {result}"
    except SyntaxError:
        return "❌ 语法错误"
    except Exception as e:
        return f"❌ 执行错误: {str(e)}"


@tool
def get_weather(city: str) -> str:
    """
    查询指定城市的天气信息
    
    参数:
        city: 城市名称（如：北京、上海、广州、London、New York）
    """
    try:
        import requests
        
        url = f"http://wttr.in/{city}?format=j1"
        response = requests.get(url, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            current_condition = data.get("current_condition", [])
            
            if current_condition:
                cc = current_condition[0]
                temp_c = cc.get("temp_C", "N/A")
                temp_f = cc.get("temp_F", "N/A")
                humidity = cc.get("humidity", "N/A")
                wind = cc.get("windspeedKmph", "N/A")
                desc = cc.get("weatherDesc", [{}])[0].get("value", "")
                feels_like = cc.get("FeelsLikeC", "N/A")
                
                return f"""📍 {city} 天气信息
🌡️ 温度: {temp_c}°C ({temp_f}°F)
❄️ 体感温度: {feels_like}°C
💧 湿度: {humidity}%
💨 风速: {wind} km/h
📝 天气状况: {desc}"""
            return f"无法获取 {city} 的详细天气信息"
        return f"❌ 请求失败，状态码: {response.status_code}"
        
    except ImportError:
        return "❌ 请安装 requests 包: pip install requests"
    except json.JSONDecodeError:
        return f"❌ 解析天气数据失败"
    except Exception as e:
        return f"❌ 天气查询错误: {str(e)}"


@tool
def github_search(query: str, sort: str = "stars", order: str = "desc") -> str:
    """
    搜索 GitHub 仓库
    
    参数:
        query: 搜索关键词（如：langchain、python、AI agent）
        sort: 排序方式（stars、forks、updated，默认 stars）
        order: 排序顺序（desc 降序、asc 升序，默认 desc）
    """
    try:
        import requests
        
        url = "https://api.github.com/search/repositories"
        params = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": 5
        }
        
        response = requests.get(url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            
            if items:
                results = []
                for item in items[:5]:
                    name = item.get("full_name", "")
                    desc = item.get("description", "")
                    stars = item.get("stargazers_count", 0)
                    forks = item.get("forks_count", 0)
                    url = item.get("html_url", "")
                    lang = item.get("language", "")
                    
                    results.append(
                        f"📦 {name}\n"
                        f"⭐ Stars: {stars:,} | 🍴 Forks: {forks:,}\n"
                        f"💻 语言: {lang}\n"
                        f"📝 描述: {desc[:100]}..." if len(desc) > 100 else f"📝 描述: {desc}\n"
                        f"🔗 {url}"
                    )
                return "\n\n".join(results)
            return "未找到相关仓库"
        elif response.status_code == 422:
            return "❌ 搜索参数无效，请检查关键词格式"
        else:
            return f"❌ 请求失败，状态码: {response.status_code}"
            
    except ImportError:
        return "❌ 请安装 requests 包: pip install requests"
    except json.JSONDecodeError:
        return "❌ 解析 GitHub 数据失败"
    except Exception as e:
        return f"❌ GitHub 搜索错误: {str(e)}"


@tool
def generate_chart(data: str, chart_type: str = "bar", title: str = "Chart") -> str:
    """
    生成数据可视化图表并保存为图片
    
    参数:
        data: JSON 格式的数据，例如: {"labels": ["A","B","C"], "values": [10,20,30]}
        chart_type: 图表类型（bar 柱状图、line 折线图、pie 饼图，默认 bar）
        title: 图表标题（默认 Chart）
    """
    try:
        import matplotlib.pyplot as plt
        import io
        
        try:
            data_dict = json.loads(data)
        except json.JSONDecodeError:
            return "❌ 数据格式错误，请提供有效的 JSON 格式数据"
            
        labels = data_dict.get("labels", [])
        values = data_dict.get("values", [])
        
        if not labels or not values:
            return "❌ 数据不能为空，需要 labels 和 values 字段"
            
        if len(labels) != len(values):
            return "❌ labels 和 values 的数量必须一致"
            
        plt.figure(figsize=(8, 6))
        
        if chart_type == "pie":
            plt.pie(values, labels=labels, autopct='%1.1f%%', startangle=90)
            plt.title(title)
        elif chart_type == "line":
            plt.plot(labels, values, marker='o', linestyle='-', color='b')
            plt.title(title)
            plt.xlabel('Categories')
            plt.ylabel('Values')
            plt.grid(True)
        else:
            plt.bar(labels, values, color='skyblue')
            plt.title(title)
            plt.xlabel('Categories')
            plt.ylabel('Values')
        
        plt.tight_layout()
        
        filename = f"chart_{int(datetime.now().timestamp())}.png"
        plt.savefig(filename, dpi=100)
        plt.close()
        
        return f"✅ 图表已生成并保存为: {filename}"
        
    except ImportError:
        return "❌ 请安装 matplotlib 包: pip install matplotlib"
    except Exception as e:
        return f"❌ 图表生成错误: {str(e)}"


@tool
def get_etf_info(etf_code: str) -> str:
    """
    查询 ETF 基本信息
    
    参数:
        etf_code: ETF 代码（如：510300、510500、159919）
    """
    if not etf_code or not etf_code.strip():
        return "❌ ETF 代码不能为空"
    
    if not etf_code.strip().isdigit():
        return "❌ ETF 代码必须为数字"
    
    try:
        import akshare as ak
        import threading
        import time
        
        result = {"name": etf_code, "full_name": "N/A", "manager": "N/A", 
                  "establish_date": "N/A", "total_assets": "N/A", 
                  "unit_nav": "N/A", "nav_date": "N/A", "risk_level": "N/A"}
        
        def fetch_info():
            try:
                df = ak.fund_etf_fund_info_em(etf_code)
                if df is not None and len(df) > 0:
                    info = df.iloc[0]
                    result["name"] = str(info.get("基金名称", etf_code))
                    result["full_name"] = str(info.get("基金全称", "N/A"))
                    result["manager"] = str(info.get("基金管理人", "N/A"))
                    result["establish_date"] = str(info.get("成立日期", "N/A"))
                    result["total_assets"] = str(info.get("最新规模", "N/A"))
                    result["unit_nav"] = str(info.get("最新净值", "N/A"))
                    result["nav_date"] = str(info.get("净值日期", "N/A"))
                    result["risk_level"] = str(info.get("风险等级", "N/A"))
            except:
                pass
        
        thread = threading.Thread(target=fetch_info)
        thread.start()
        thread.join(timeout=30)
        
        if result["name"] == etf_code:
            spot_df = ak.fund_etf_spot_em()
            if spot_df is not None and len(spot_df) > 0:
                etf_data = spot_df[spot_df["代码"] == etf_code]
                if len(etf_data) > 0:
                    info = etf_data.iloc[0]
                    result["name"] = str(info.get("名称", etf_code))
        
        return f"""📊 {result['name']} ({etf_code}) 基本信息
📝 基金全称: {result['full_name']}
🏢 基金管理人: {result['manager']}
📅 成立日期: {result['establish_date']}
💰 最新规模: {result['total_assets']}
📈 最新净值: {result['unit_nav']} ({result['nav_date']})
⚠️ 风险等级: {result['risk_level']}"""
        
    except ImportError:
        return "❌ 请安装 akshare 包: pip install akshare"
    except Exception as e:
        return f"❌ ETF 信息查询错误: {str(e)}"


@tool
def get_etf_price(etf_code: str) -> str:
    """
    查询 ETF 实时行情
    
    参数:
        etf_code: ETF 代码（如：510300、510500、159919）
    """
    if not etf_code or not etf_code.strip():
        return "❌ ETF 代码不能为空"
    
    if not etf_code.strip().isdigit():
        return "❌ ETF 代码必须为数字"
    
    try:
        import akshare as ak
        import threading
        
        result = {"success": False, "data": None}
        
        def fetch_price():
            try:
                df = ak.fund_etf_spot_em()
                if df is not None and len(df) > 0:
                    etf_data = df[df["代码"] == etf_code]
                    if len(etf_data) > 0:
                        result["data"] = etf_data.iloc[0]
                        result["success"] = True
            except:
                pass
        
        thread = threading.Thread(target=fetch_price)
        thread.start()
        thread.join(timeout=30)
        
        if result["success"] and result["data"] is not None:
            info = result["data"]
            
            name = str(info.get("名称", etf_code))
            price = float(info.get("最新价", 0))
            prev_close = float(info.get("昨收价", 0))
            open_price = float(info.get("开盘价", 0))
            high = float(info.get("最高价", 0))
            low = float(info.get("最低价", 0))
            
            if prev_close > 0:
                change = price - prev_close
                change_pct = (change / prev_close) * 100
            else:
                change = 0
                change_pct = 0
            
            return f"""📈 {name} ({etf_code}) 实时行情
💰 当前价格: ¥{price:.3f}
📊 涨跌幅: {'+' if change >= 0 else ''}{change:.3f} ({'+' if change_pct >= 0 else ''}{change_pct:.2f}%)
📉 开盘价: ¥{open_price:.3f}
📈 最高价: ¥{high:.3f}
📉 最低价: ¥{low:.3f}
🔄 昨收价: ¥{prev_close:.3f}"""
        return f"❌ 无法获取 ETF {etf_code} 的行情数据，请检查代码是否正确"
        
    except ImportError:
        return "❌ 请安装 akshare 包: pip install akshare"
    except ValueError:
        return f"❌ 解析行情数据失败，请检查 ETF 代码"
    except Exception as e:
        return f"❌ ETF 行情查询错误: {str(e)}"


@tool
def get_etf_history(etf_code: str, days: int = 30) -> str:
    """
    查询 ETF 历史行情数据
    
    参数:
        etf_code: ETF 代码（如：510300、510500、159919）
        days: 查询天数（默认 30 天，最大 365 天）
    """
    try:
        import akshare as ak
        from datetime import datetime, timedelta
        import threading
        
        result = {"success": False, "data": None}
        
        def fetch_history():
            try:
                days_local = min(days, 365)
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=days_local)).strftime("%Y%m%d")
                df = ak.fund_etf_hist_em(symbol=etf_code, period="daily", start_date=start_date, end_date=end_date)
                if df is not None and len(df) > 0:
                    result["data"] = df.tail(10)
                    result["success"] = True
            except:
                pass
        
        thread = threading.Thread(target=fetch_history)
        thread.start()
        thread.join(timeout=30)
        
        if result["success"] and result["data"] is not None:
            df = result["data"]
            
            results = []
            for _, row in df.iterrows():
                date = str(row.get("日期", ""))
                close = float(row.get("收盘", 0))
                change = float(row.get("涨跌额", 0))
                change_pct = float(row.get("涨跌幅", 0))
                
                results.append(
                    f"📅 {date}: ¥{close:.3f} "
                    f"({'+' if change >= 0 else ''}{change:.3f} "
                    f"({'+' if change_pct >= 0 else ''}{change_pct:.2f}%)"
                )
            
            return f"""📊 {etf_code} 最近 {len(results)} 天历史行情
{'─' * 60}
{'\n'.join(results)}
{'─' * 60}
💡 如需查看完整走势图，请使用 generate_chart 工具生成图表"""
        return f"❌ 无法获取 ETF {etf_code} 的历史数据"
        
    except ImportError:
        return "❌ 请安装 akshare 包: pip install akshare"
    except Exception as e:
        return f"❌ ETF 历史数据查询错误: {str(e)}"


@tool
def get_etf_knowledge(topic: str = "basic") -> str:
    """
    获取 ETF 相关知识
    
    参数:
        topic: 知识主题（basic: 基础概念, types: 类型介绍, how_to_buy: 购买指南, risks: 风险提示, all: 全部）
    """
    knowledge_base = {
        "basic": """📚 ETF 基础概念

ETF (Exchange Traded Fund) 即交易型开放式指数基金，是一种在交易所上市交易的开放式基金。

🔹 主要特点：
- 像股票一样在交易所实时交易
- 跟踪特定指数（如沪深300、纳斯达克100）
- 分散投资，降低单一股票风险
- 费用通常低于传统基金
- 透明度高，持仓公开

🔹 与股票的区别：
- ETF 一篮子股票，股票是单一公司
- ETF 风险分散，股票风险集中
- ETF 通常有更低的波动率""",

        "types": """📊 ETF 类型介绍

🔹 按投资标的分类：
1. 股票型 ETF：跟踪股票指数（如 510300 沪深300ETF）
2. 债券型 ETF：投资债券（如 511260 国债ETF）
3. 商品型 ETF：投资黄金、原油等（如 518880 黄金ETF）
4. 货币型 ETF：投资货币市场工具
5. 跨境 ETF：投资海外市场（如 513100 纳指ETF）

🔹 常见宽基 ETF：
- 510300: 沪深300ETF
- 510500: 中证500ETF
- 159919: 创业板ETF
- 513100: 纳斯达克100ETF
- 513500: 标普500ETF""",

        "how_to_buy": """🛒 ETF 购买指南

🔹 购买渠道：
1. 证券账户：通过股票交易软件购买（最常见）
2. 基金平台：支付宝、天天基金等
3. 银行渠道：柜台或手机银行

🔹 交易规则：
- 交易时间：9:30-11:30, 13:00-15:00
- 最小交易单位：1手（100份）
- T+1 交收（部分跨境ETF可能不同）
- 费用：佣金（通常万分之2.5）、印花税（无）

🔹 注意事项：
- 选择流动性好的 ETF
- 关注跟踪误差
- 了解折溢价情况""",

        "risks": """⚠️ ETF 风险提示

🔹 市场风险：
- 跟踪指数下跌导致净值亏损
- 宏观经济变化影响整体市场

🔹 特殊风险：
- 折溢价风险：市价与净值偏离
- 流动性风险：交易量不足难以卖出
- 跟踪误差：未能完全复制指数收益
- 跨境风险：汇率波动、政策变化

🔹 风险管理建议：
- 分散投资，不要重仓单一 ETF
- 关注基金规模（建议 >2 亿）
- 长期投资，避免频繁交易""",

        "all": """📚 ETF 完整知识

---
📚 ETF 基础概念
ETF (Exchange Traded Fund) 即交易型开放式指数基金，像股票一样在交易所交易，跟踪特定指数。

---
📊 ETF 类型
- 股票型: 510300 沪深300ETF
- 债券型: 511260 国债ETF
- 商品型: 518880 黄金ETF
- 跨境型: 513100 纳指ETF

---
🛒 购买方式
通过证券账户购买，T+1交收，最低1手（100份）。

---
⚠️ 风险提示
市场风险、折溢价风险、流动性风险。建议分散投资。"""
    }
    
    return knowledge_base.get(topic, f"❌ 未知主题: {topic}。可用主题: basic, types, how_to_buy, risks, all")


@tool
def compare_etfs(etf_codes: str) -> str:
    """
    对比分析多个 ETF
    
    参数:
        etf_codes: ETF 代码列表，用逗号分隔（如：510300,510500,159919）
    """
    try:
        codes = [code.strip() for code in etf_codes.split(",")]
        if len(codes) < 2:
            return "❌ 请至少输入两个 ETF 代码进行对比"
        
        results = []
        for code in codes:
            info = get_etf_info.invoke({"etf_code": code})
            price = get_etf_price.invoke({"etf_code": code})
            
            if "❌" not in info:
                lines = info.split("\n")
                name_line = [l for l in lines if "基本信息" in l][0] if any("基本信息" in l for l in lines) else code
                scale_line = [l for l in lines if "规模" in l][0] if any("规模" in l for l in lines) else ""
                risk_line = [l for l in lines if "风险" in l][0] if any("风险" in l for l in lines) else ""
                
                if "❌" not in price:
                    price_lines = price.split("\n")
                    price_line = [l for l in price_lines if "当前价格" in l][0] if any("当前价格" in l for l in price_lines) else ""
                    change_line = [l for l in price_lines if "涨跌幅" in l][0] if any("涨跌幅" in l for l in price_lines) else ""
                else:
                    price_line = ""
                    change_line = ""
                
                results.append(f"{name_line}\n{scale_line}\n{risk_line}\n{price_line}\n{change_line}")
        
        if not results:
            return "❌ 无法获取任何 ETF 的信息"
        
        return "📊 ETF 对比分析\n" + "\n" + "─" * 60 + "\n".join(results)
        
    except Exception as e:
        return f"❌ ETF 对比分析错误: {str(e)}"


@tool
def etf_analysis(etf_code: str, days: int = 30) -> str:
    """
    ETF 综合分析与预测
    
    参数:
        etf_code: ETF 代码（如：510300、510500、159919）
        days: 分析天数（默认 30 天）
    """
    try:
        import akshare as ak
        import statistics
        from datetime import datetime, timedelta
        import threading
        
        result = {"success": False, "closes": [], "changes": []}
        
        def fetch_data():
            try:
                days_local = min(days, 365)
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=days_local)).strftime("%Y%m%d")
                df = ak.fund_etf_hist_em(symbol=etf_code, period="daily", start_date=start_date, end_date=end_date)
                if df is not None and len(df) > 0:
                    result["closes"] = [float(row.get("收盘", 0)) for _, row in df.iterrows()]
                    result["changes"] = [float(row.get("涨跌幅", 0)) for _, row in df.iterrows()]
                    result["success"] = True
            except:
                pass
        
        thread = threading.Thread(target=fetch_data)
        thread.start()
        thread.join(timeout=30)
        
        if result["success"] and len(result["closes"]) >= 5:
            closes = result["closes"]
            changes = result["changes"]
            
            current_price = closes[-1]
            avg_price = sum(closes) / len(closes)
            max_price = max(closes)
            min_price = min(closes)
            volatility = statistics.stdev(changes) if len(changes) > 1 else 0
            avg_change = sum(changes) / len(changes)
            positive_days = sum(1 for c in changes if c > 0)
            negative_days = sum(1 for c in changes if c < 0)
            
            analysis = []
            analysis.append(f"📊 {etf_code} 综合分析报告")
            analysis.append(f"{'─' * 60}")
            analysis.append(f"📈 当前价格: ¥{current_price:.3f}")
            analysis.append(f"📊 平均价格: ¥{avg_price:.3f}")
            analysis.append(f"🔝 最高价: ¥{max_price:.3f}")
            analysis.append(f"🔻 最低价: ¥{min_price:.3f}")
            analysis.append(f"📉 波动率: {volatility:.2f}%")
            analysis.append(f"📈 平均日涨跌: {'+' if avg_change >= 0 else ''}{avg_change:.2f}%")
            analysis.append(f"✅ 上涨天数: {positive_days} 天")
            analysis.append(f"❌ 下跌天数: {negative_days} 天")
            analysis.append(f"{'─' * 60}")
            
            if current_price > avg_price:
                analysis.append("💡 价格高于近期平均，注意回调风险")
            else:
                analysis.append("💡 价格低于近期平均，可能存在买入机会")
            
            if volatility > 3:
                analysis.append("⚠️ 波动率较高，风险偏大")
            elif volatility < 1:
                analysis.append("📌 波动率较低，走势相对稳定")
            
            if avg_change > 0:
                analysis.append("📈 近期整体呈上涨趋势")
            else:
                analysis.append("📉 近期整体呈下跌趋势")
            
            analysis.append("")
            analysis.append("⚠️ 免责声明：以上分析仅供参考，不构成投资建议")
            
            return "\n".join(analysis)
        return f"❌ 无法获取 ETF {etf_code} 的历史数据"
        
    except ImportError:
        return "❌ 请安装 akshare 包: pip install akshare"
    except Exception as e:
        return f"❌ ETF 分析错误: {str(e)}"


def get_all_tools():
    return [
        get_current_time, 
        calculate, 
        search_web, 
        query_knowledge_base, 
        load_knowledge_base,
        read_file,
        write_file,
        list_files,
        run_code,
        get_weather,
        github_search,
        generate_chart,
        get_etf_info,
        get_etf_price,
        get_etf_history,
        get_etf_knowledge,
        compare_etfs,
        etf_analysis
    ]