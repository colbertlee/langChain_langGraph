# -*- coding: utf-8 -*-
"""RAG 模块独立测试 harness —— 公共助手。

本测试只使用 knowledge_base/*.txt 作为被测文档（KB 级），不引入外部知识库。
"""
import os
import sys

from langchain_core.messages import AIMessage
from langchain_core.runnables import Runnable

AGENT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if AGENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_DIR)

KB_DIR = os.path.join(AGENT_DIR, "knowledge_base")

# ---------------------------------------------------------------------------
# 环境依赖漂移缺陷缓解：langchain-chroma 0.2.6 引用 chromadb 0.6+ 的
# CreateCollectionConfiguration，但环境里是 chromadb 0.5.23（requirements 锁定
# chromadb~=0.4.0 / langchain-chroma~=0.1.0，均被违反）→ 顶层 `from langchain_chroma
# import Chroma` 崩溃。此处注入最小 stub，仅用于"隔离导入，让模块逻辑可测"，
# 不改动 shared venv。真实缺陷在报告中单独记录。
# ---------------------------------------------------------------------------
import types as _types

def enable_langchain_chroma_shim():
    if "langchain_chroma" in sys.modules:
        return
    fake = _types.ModuleType("langchain_chroma")
    class _ChromaStub:
        def __init__(self, *a, **k):
            raise RuntimeError("langchain_chroma 被环境缺陷阻止（chromadb版本不匹配），"
                               "未实例化。请先修复依赖并移除 common.enable_langchain_chroma_shim 的 shim。")
        @staticmethod
        def from_documents(*a, **k):
            raise RuntimeError("langchain_chroma 不可用（环境缺陷），请修复依赖。")
    fake.Chroma = _ChromaStub
    sys.modules["langchain_chroma"] = fake

enable_langchain_chroma_shim()

KB_FILES = [
    "python_intro.txt",
    "javascript_intro.txt",
    "java_intro.txt",
    "cooking_basics.txt",
    "travel_guide.txt",
    "photography.txt",
    "fitness.txt",
    "gardening.txt",
]

def kb_path(fname: str) -> str:
    return os.path.join(KB_DIR, fname)

def read_raw_bytes(fname: str) -> bytes:
    """原始字节读取（不做任何解码），用于模块1比对原文。"""
    with open(kb_path(fname), "rb") as f:
        return f.read()

def read_raw_text(fname: str) -> str:
    """以 UTF-8 精确读取源文件，作为"原文"基准。"""
    with open(kb_path(fname), "r", encoding="utf-8") as f:
        return f.read()

# ---------------------------------------------------------------------------
# 结构化报告输出：按用户要求的【模块】【测试用例】【预期】【实际】【通过】【缺陷】
# ---------------------------------------------------------------------------
class ModuleReport:
    def __init__(self, name):
        self.name = name
        self.cases = []  # (case, expected, actual, passed)
        self.defects = []
        self.notes = []

    def add(self, case, expected, actual, passed):
        self.cases.append((case, expected, actual, passed))

    def defect(self, detail):
        self.defects.append(detail)

    def note(self, detail):
        """信息性备注，不计入失败，不阻断 all_pass。"""
        self.notes.append(detail)

    def render(self):
        lines = []
        lines.append("=" * 78)
        lines.append("【模块】" + self.name)
        lines.append("=" * 78)
        for case, expected, actual, passed in self.cases:
            mark = "通过" if passed else "失败"
            lines.append("-" * 78)
            lines.append("[测试用例] " + str(case))
            lines.append("[预期标准]  " + str(expected))
            lines.append("[实际结果]  " + str(actual))
            lines.append("[是否通过]  " + mark)
        lines.append("-" * 78)
        if self.defects:
            lines.append("[缺陷详情]")
            for d in self.defects:
                lines.append("  - " + d)
        else:
            lines.append("[缺陷详情] 无")
        if self.notes:
            lines.append("[备注(信息性)]")
            for n in self.notes:
                lines.append("  * " + n)
        print("\n".join(lines))
        return self.passed_total

    @property
    def passed_total(self):
        return sum(1 for _, _, _, p in self.cases if p)

    @property
    def total(self):
        return len(self.cases)

    @property
    def all_pass(self):
        return self.total > 0 and self.passed_total == self.total and not self.defects


# ---------------------------------------------------------------------------
# ChatOllama 替代：直接调本机 Ollama /api/chat。
# 继承 Runnable 以接入 LangChain 管道（PROMPT | LLM | StrOutputParser()）。
# 之所以存在：当前环境 `langchain-community.chat_models.ChatOllama` 已被移除，
# 且未安装 `langchain-ollama`。供 m6/m8 等需要 LLM 的测试模块共用。
# ---------------------------------------------------------------------------
class OllamaChat(Runnable):
    def __init__(self, model: str, base_url: str = "http://localhost:11434",
                 temperature: float = 0.1, timeout: int = 300):
        import requests as _req
        super().__init__()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = float(temperature)
        self.timeout = int(timeout)
        self._req = _req

    @staticmethod
    def _format_messages(messages):
        # langchain 的 BaseMessage 列表 -> ollama {role, content}
        role_map = {"human": "user", "ai": "assistant", "system": "system"}
        out = []
        for m in messages:
            role = getattr(m, "type", None) or m.__class__.__name__.lower()
            out.append({"role": role_map.get(role, role), "content": m.content})
        return out

    def invoke(self, input, config=None, **kwargs):
        # 上游 ChatPromptTemplate 输出 PromptValue（有 to_messages）；
        # 纯字符串则按 user 处理；其余按 BaseMessage 列表处理
        if isinstance(input, str):
            messages = [{"role": "user", "content": input}]
        elif hasattr(input, "to_messages"):
            messages = self._format_messages(input.to_messages())
        else:
            messages = self._format_messages(input)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # qwen3.5 为 thinking 模型，关闭思考以控制测试时长
            "options": {"temperature": self.temperature},
        }
        r = self._req.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        # ollama 返回 {message:{role,content}, ...}
        msg = (data.get("message") or {})
        return AIMessage(content=msg.get("content") or "")