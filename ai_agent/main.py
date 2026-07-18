from agent import AIAgent
import sys


def print_banner():
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                    AI Agent 智能助手                         ║
║              Powered by LangChain + LangGraph               ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(banner)


def print_help():
    help_text = """
可用命令:
  exit / quit     - 退出程序
  clear           - 清除对话历史
  help            - 显示帮助信息
  tools           - 列出所有可用工具
  history         - 显示对话历史数量
  version         - 显示版本信息
  
工具列表:
  get_current_time     - 获取当前时间
  calculate            - 数学计算
  search_web           - 网络搜索
  query_knowledge_base - 查询知识库
  load_knowledge_base  - 加载文档到知识库
  read_file            - 读取文件内容
  write_file           - 写入文件内容
  list_files           - 列出目录文件
  run_code             - 执行简单Python代码
  
示例:
  现在几点了？
  计算 2 + 3 * 4
  加载文档 knowledge_base/python_intro.txt
  Python 有哪些特点？
  读取文件 README.md
  列出当前目录
  执行代码 2**10
"""
    print(help_text)


def main():
    print_banner()
    print("输入 'help' 查看帮助信息")
    print("=" * 60)
    
    agent = AIAgent()
    print(f"✅ Agent 初始化成功，可用工具: {len(agent.get_tools_list())} 个")
    
    while True:
        try:
            user_input = input("\n你: ").strip()
            
            if not user_input:
                print("AI: 请输入内容")
                continue
            
            if user_input.lower() in ["exit", "quit"]:
                print("\nAI: 再见！感谢使用！")
                break
            
            if user_input.lower() == "clear":
                result = agent.clear_history()
                print(f"\nAI: {result}")
                continue
            
            if user_input.lower() == "help":
                print_help()
                continue
            
            if user_input.lower() == "tools":
                tools = agent.get_tools_list()
                print(f"\nAI: 可用工具 ({len(tools)} 个):")
                for i, tool in enumerate(tools, 1):
                    print(f"  {i}. {tool}")
                continue
            
            if user_input.lower() == "history":
                print("\nAI: 对话历史存储在 memory.db 中")
                continue
            
            if user_input.lower() == "version":
                print("\nAI Agent v1.0.0")
                print("基于 LangChain 1.x + LangGraph")
                continue
            
            print("\nAI: ", end="", flush=True)
            
            for chunk in agent.run_stream(user_input):
                print(chunk, end="", flush=True)
            print()
            
        except KeyboardInterrupt:
            print("\n\nAI: 程序已中断")
            break
        except EOFError:
            print("\n\nAI: 输入结束")
            break
        except Exception as e:
            print(f"\nAI: ❌ 错误: {str(e)}")


if __name__ == "__main__":
    main()