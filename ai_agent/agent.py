import sqlite3
import logging
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver

from config import OPENAI_API_KEY, MODEL_NAME, TEMPERATURE, LOG_LEVEL
from tools import get_all_tools, set_rag_instance
from rag import RAGModule
from security import SecurityModule, set_security_instance


logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("agent.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class AIAgent:
    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.model = None
        self.rag = None
        self.security = None
        self.tools = get_all_tools()
        self.checkpointer = None
        self.agent = None
        
        conn = sqlite3.connect("memory.db")
        self.checkpointer = SqliteSaver(conn)
        
        self.system_prompt = """你是一个智能助手，能够使用以下工具：
- get_current_time: 获取当前时间
- calculate: 进行数学计算
- search_web: 搜索网络信息
- query_knowledge_base: 查询知识库文档
- load_knowledge_base: 加载文档到知识库
- read_file: 读取文件内容
- write_file: 写入文件内容
- list_files: 列出目录文件
- run_code: 执行简单Python代码
- get_weather: 查询指定城市的天气信息
- github_search: 搜索GitHub仓库
- generate_chart: 生成数据可视化图表（支持柱状图、折线图、饼图）
- get_etf_info: 查询ETF基本信息（代码、名称、规模、风险等级等）
- get_etf_price: 查询ETF实时行情（价格、涨跌幅、开盘价等）
- get_etf_history: 查询ETF历史行情数据（支持自定义天数）
- get_etf_knowledge: 获取ETF相关知识（基础概念、类型、购买指南、风险提示）
- compare_etfs: 对比分析多个ETF
- etf_analysis: ETF综合分析与预测（波动率、趋势判断等）

请根据用户的需求，选择合适的工具。如果不需要使用工具，可以直接回答用户。

回答要友好、简洁、准确。"""
    
    def init_agent(self):
        if self.api_key:
            self.model = ChatOpenAI(
                model=MODEL_NAME,
                temperature=TEMPERATURE,
                api_key=self.api_key
            )
            
            self.rag = RAGModule(self.model, api_key=self.api_key)
            set_rag_instance(self.rag)
            
            self.security = SecurityModule()
            set_security_instance(self.security)
            
            self.tools = get_all_tools()
            
            self.agent = create_agent(
                model=self.model,
                tools=self.tools,
                system_prompt=self.system_prompt,
                checkpointer=self.checkpointer
            )
    
    def set_api_key(self, api_key: str):
        self.api_key = api_key
        self.model = None
        self.agent = None
        self.init_agent()
    
    def get_api_key_status(self):
        return {"configured": bool(self.api_key), "has_agent": self.agent is not None}
    
    def run(self, user_input: str) -> str:
        try:
            logger.info(f"User input: {user_input}")
            
            if not self.agent:
                self.init_agent()
            
            if not self.agent:
                return "❌ 错误: 请先配置 API Key。\n\n点击右上角的 ⚙️ 按钮配置 OpenAI API Key。"
            
            security_check = self.security.check_input(user_input)
            if security_check["blocked"]:
                logger.warning(f"Input blocked: {security_check['reason']}")
                return f"❌ 输入被阻止: {security_check['reason']}"
            
            response = self.agent.invoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config={"configurable": {"thread_id": "default"}}
            )
            
            output = response.get("output", "")
            
            output_check = self.security.check_output(output)
            if output_check["blocked"]:
                logger.warning("Output blocked: contains sensitive information")
                return "❌ 输出被阻止: 包含敏感信息"
            
            sanitized_output = self.security.sanitize_output(output)
            logger.info(f"Agent output: {sanitized_output[:100]}...")
            
            return sanitized_output
            
        except Exception as e:
            logger.error(f"Error: {str(e)}")
            error_str = str(e)
            if "timeout" in error_str.lower() or "timed out" in error_str.lower():
                return "❌ 错误: 请求超时，请检查网络连接或稍后重试。"
            if "api key" in error_str.lower() or "unauthorized" in error_str.lower():
                return "❌ 错误: API Key 无效或未配置。\n\n请在 .env 文件中添加：\nOPENAI_API_KEY=your_api_key_here"
            return f"❌ 错误: {error_str}"
    
    def run_stream(self, user_input: str):
        try:
            logger.info(f"Streaming user input: {user_input}")
            
            if not self.agent:
                self.init_agent()
            
            if not self.agent:
                yield "❌ 错误: 请先配置 API Key。\n\n点击右上角的 ⚙️ 按钮配置 OpenAI API Key。"
                return
            
            security_check = self.security.check_input(user_input)
            if security_check["blocked"]:
                logger.warning(f"Input blocked: {security_check['reason']}")
                yield f"❌ 输入被阻止: {security_check['reason']}"
                return
            
            last_content_length = 0
            for chunk in self.agent.stream(
                {"messages": [{"role": "user", "content": user_input}]},
                config={"configurable": {"thread_id": "default"}},
                stream_mode="values"
            ):
                messages = chunk.get("messages", [])
                if messages:
                    last_message = messages[-1]
                    if hasattr(last_message, 'content'):
                        content = last_message.content
                        if content:
                            sanitized_output = self.security.sanitize_output(content)
                            incremental_content = sanitized_output[last_content_length:]
                            if incremental_content:
                                yield incremental_content
                                last_content_length = len(sanitized_output)
            
            logger.info("Streaming completed")
            
        except Exception as e:
            logger.error(f"Streaming error: {str(e)}")
            error_str = str(e)
            if "timeout" in error_str.lower() or "timed out" in error_str.lower():
                yield "❌ 错误: 请求超时，请检查网络连接或稍后重试。"
            elif "api key" in error_str.lower() or "unauthorized" in error_str.lower():
                yield "❌ 错误: API Key 无效或未配置。\n\n请在 .env 文件中添加：\nOPENAI_API_KEY=your_api_key_here"
            else:
                yield f"❌ 错误: {error_str}"
    
    def clear_history(self):
        try:
            self.checkpointer.clear()
            logger.info("History cleared")
            return "✅ 对话历史已清除"
        except Exception as e:
            logger.error(f"Clear history error: {str(e)}")
            return f"❌ 清除历史失败: {str(e)}"
    
    def get_tools_list(self):
        if self.tools is None:
            return []
        return [tool.name for tool in self.tools]