import sqlite3
import logging
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langgraph.checkpoint.sqlite import SqliteSaver
from config import OPENAI_API_KEY, MODEL_NAME, TEMPERATURE, LOG_LEVEL
from tools import get_all_tools, set_rag_instance
from rag import RAGModule
from security import SecurityModule, set_security_instance

logging.basicConfig(level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("agent.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

class AIAgent:
    def __init__(self):
        self.api_key = OPENAI_API_KEY
        self.model = None
        self.rag = None
        self.security = None
        self.tools = get_all_tools()
        conn = sqlite3.connect("memory.db")
        self.checkpointer = SqliteSaver(conn)
        self.system_prompt = """You are an AI assistant with these tools:
- get_current_time, calculate, search_web, query_knowledge_base
- read_file, write_file, list_files, run_code
- get_weather, github_search, generate_chart"""
    
    def init_agent(self):
        if self.api_key:
            self.model = ChatOpenAI(model=MODEL_NAME, temperature=TEMPERATURE, api_key=self.api_key)
            self.rag = RAGModule(self.model, api_key=self.api_key)
            set_rag_instance(self.rag)
            self.security = SecurityModule()
            set_security_instance(self.security)
            self.tools = get_all_tools()
            self.agent = create_agent(model=self.model, tools=self.tools,
                system_prompt=self.system_prompt, checkpointer=self.checkpointer)
    
    def set_api_key(self, api_key):
        self.api_key = api_key
        self.init_agent()
    
    def get_api_key_status(self):
        return {"configured": bool(self.api_key), "has_agent": self.agent is not None}
    
    def run(self, user_input):
        try:
            if not self.agent:
                self.init_agent()
            if not self.agent:
                return "Configure API Key"
            response = self.agent.invoke({"messages": [{"role": "user", "content": user_input}]},
                config={"configurable": {"thread_id": "default"}})
            return self.security.sanitize_output(response.get("output", ""))
        except Exception as e:
            return f"Error: {str(e)}"
    
    def run_stream(self, user_input):
        try:
            if not self.agent:
                self.init_agent()
            if not self.agent:
                yield "Configure API Key"
                return
            last_len = 0
            for chunk in self.agent.stream({"messages": [{"role": "user", "content": user_input}]},
                    config={"configurable": {"thread_id": "default"}}, stream_mode="values"):
                msgs = chunk.get("messages", [])
                if msgs and hasattr(msgs[-1], 'content') and msgs[-1].content:
                    s = self.security.sanitize_output(msgs[-1].content)
                    inc = s[last_len:]
                    if inc:
                        yield inc
                        last_len = len(s)
        except Exception as e:
            yield f"Error: {str(e)}"
    
    def clear_history(self):
        self.checkpointer.clear()
        return "Cleared"
    
    def get_tools_list(self):
        return [t.name for t in self.tools] if self.tools else []