from __future__ import annotations

import os
from typing import Callable, Dict, List, Optional

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.documents import Document

from config import OPENAI_API_KEY, EMBEDDING_API_KEY, EMBEDDING_MODEL_TYPE


def get_embedding_model(model_type="openai", api_key=None):
    """
    获取 Embedding 模型，支持多种模型。

    已迁移到 plugins.rag_backends.registry.EmbeddingBackendRegistry。
    保留参数 / 行为完全兼容旧代码。

    Args:
        model_type: 模型类型 (openai/zhipu/ollama/...)，未注册时回退 openai
        api_key: API Key

    Returns:
        Embedding 实例（langchain Embeddings）
    """
    # 优先走 plugin registry；未注册则按旧实现逐个 try。
    try:
        from plugins.rag_backends.registry import EmbeddingBackendRegistry
        backend = EmbeddingBackendRegistry.create(
            model_type, {"api_key": api_key}
        )
        print(f"[INFO] Using embedding backend: {backend.display_name}")
        return backend.as_langchain_embeddings()
    except KeyError:
        pass

    # ---- 旧实现：作为兜底保留 ----
    # 使用传入的 api_key 或配置的 EMBEDDING_API_KEY
    key = api_key or EMBEDDING_API_KEY or OPENAI_API_KEY

    if model_type == "openai":
        print("[INFO] Using OpenAI text-embedding-3-small (1536 dimension)")
        return OpenAIEmbeddings(api_key=key)
    
    elif model_type == "minimax":
        try:
            from langchain_community.embeddings import MiniMaxEmbeddings
            print("[INFO] Using MiniMax embo-01 (1024 dimension)")
            return MiniMaxEmbeddings(
                mini_max_api_key=key,
                model_name="embo-01"
            )
        except ImportError:
            print("[WARN] Please install: pip install langchain-community")
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)
    
    elif model_type == "zhipu":
        try:
            from langchain_community.embeddings import ZhipuAIEmbeddings
            print("[INFO] Using Zhipu embedding-2 (1024 dimension)")
            print("[INFO] API: https://open.bigmodel.cn/api/paas/v4/")
            return ZhipuAIEmbeddings(
                api_key=key,
                model="embedding-2",
                zhipuai_api_base="https://open.bigmodel.cn/api/paas/v4/"
            )
        except ImportError:
            print("[WARN] Please install: pip install langchain-community")
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)
    
    elif model_type == "jina":
        try:
            from langchain_community.embeddings import JinaEmbeddings
            print("[INFO] Using Jina AI jina-embeddings-v3 (1024 dimension)")
            return JinaEmbeddings(
                jina_api_key=key,
                model_name="jina-embeddings-v3"
            )
        except ImportError:
            print("[WARN] Please install: pip install langchain-community")
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)
    
    elif model_type == "ollama":
        try:
            from langchain_community.embeddings import OllamaEmbeddings
            print("[INFO] Using Ollama local model (free, no API Key)")
            print("[INFO] Default model: mxbai-embed-large")
            return OllamaEmbeddings(
                model="mxbai-embed-large",
                base_url="http://localhost:11434"
            )
        except ImportError:
            print("[WARN] Please install: pip install langchain-community")
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)
    
    else:
        print("[WARN] Unsupported model type: {}, using OpenAI".format(model_type))
        return OpenAIEmbeddings(api_key=key)


# ============================================================
# Day 11-12：多格式文档加载器
# ============================================================


class DocumentLoaderRegistry:
    """按扩展名路由到对应 ``langchain_community`` loader。

    支持的格式（依赖缺失时给出"如何安装"的提示而非抛 ImportError）：

    - ``.txt``         纯文本 —— ``TextLoader``（默认即支持）
    - ``.md``          Markdown —— ``UnstructuredMarkdownLoader``
    - ``.pdf``         PDF —— ``PyPDFLoader`` （要 ``pip install pypdf``）
    - ``.docx`` / ``.doc``  Word —— ``Docx2txtLoader`` （要 ``pip install docx2txt``）
    - ``.csv``         CSV —— ``CSVLoader``
    - ``.json``        JSON —— ``JSONLoader`` 文本转 Document

    新格式接入方式：
        DocumentLoaderRegistry.register(".html", lambda p: BSHTMLLoader(p))
    """

    _LOADERS: Dict[str, Callable[[str], List[Document]]] = {}

    @classmethod
    def register(cls, suffix: str, factory: Callable[[str], List[Document]]) -> None:
        suffix = suffix.lower()
        if not suffix.startswith("."):
            suffix = "." + suffix
        cls._LOADERS[suffix] = factory

    @classmethod
    def supported_suffixes(cls) -> List[str]:
        return sorted(cls._LOADERS.keys())

    @classmethod
    def get(cls, suffix: str) -> Optional[Callable[[str], List[Document]]]:
        suffix = suffix.lower()
        if not suffix.startswith("."):
            suffix = "." + suffix
        return cls._LOADERS.get(suffix)

    @classmethod
    def load(cls, file_path: str) -> List[Document]:
        """根据扩展名调度 loader；缺失时回退到 TextLoader。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(file_path)
        suffix = os.path.splitext(file_path)[1].lower()
        factory = cls._LOADERS.get(suffix)
        if factory is None:
            # 回退：按文本读
            return TextLoader(file_path, encoding="utf-8").load()
        try:
            return factory(file_path)
        except ImportError as e:
            raise RuntimeError(
                f"加载 {file_path} 需要额外依赖: {e}. "
                f"请 pip install 对应包，或删除本文件。"
            ) from e


# ---- 内置 loader 注册（懒加载，缺包不报错） ----

def _register_builtin_loaders() -> None:
    """默认注册器。所有 loader 走 ``lazy_import``：仅在首次调用时 import。"""

    def text(p: str):
        return TextLoader(p, encoding="utf-8").load()

    DocumentLoaderRegistry.register(".txt", text)
    DocumentLoaderRegistry.register(".md", text)  # md 当文本读即可（前端少则 200ms 内）

    def csv_loader(p: str):
        from langchain_community.document_loaders.csv_loader import CSVLoader
        return CSVLoader(file_path=p, encoding="utf-8").load()

    DocumentLoaderRegistry.register(".csv", csv_loader)

    def json_loader(p: str):
        from langchain_community.document_loaders import JSONLoader
        # jq schema：把每个顶层元素变成一个 Document（content = JSON 字符串）
        return JSONLoader(
            file_path=p,
            jq_schema=".",
            text_content=False,
            metadata_func=lambda rec, meta: {"source": p},
        ).load()

    DocumentLoaderRegistry.register(".json", json_loader)

    def pdf_loader(p: str):
        from langchain_community.document_loaders import PyPDFLoader
        # PyPDFLoader 每页一个 Document；page metadata 自动注入
        return PyPDFLoader(p).load()

    DocumentLoaderRegistry.register(".pdf", pdf_loader)

    def docx_loader(p: str):
        from langchain_community.document_loaders import Docx2txtLoader
        return Docx2txtLoader(p).load()

    DocumentLoaderRegistry.register(".docx", docx_loader)
    DocumentLoaderRegistry.register(".doc", docx_loader)

    def html_loader(p: str):
        try:
            from langchain_community.document_loaders import BSHTMLLoader
        except ImportError:
            from langchain_community.document_loaders.html import UnstructuredHTMLLoader as _Fallback
            return _Fallback(p).load()
        return BSHTMLLoader(p, open_encoding="utf-8").load()

    DocumentLoaderRegistry.register(".html", html_loader)
    DocumentLoaderRegistry.register(".htm", html_loader)


_register_builtin_loaders()


class RAGModule:
    def __init__(self, model, api_key=None, embedding_model_type=None, vectorstore_backend: str = "chroma"):
        self.model = model
        self.api_key = api_key
        # 支持动态指定模型类型，或使用配置文件中的默认类型
        self.embedding_model_type = embedding_model_type or EMBEDDING_MODEL_TYPE or "openai"
        # 向量库后端（默认 chroma；可通过 plugin 扩展）
        self._vectorstore_backend = vectorstore_backend
        self.vectorstore = None
        self.retriever = None
        self.rag_chain = None
        
        # 获取 Embedding 模型
        self.embeddings = get_embedding_model(
            model_type=self.embedding_model_type,
            api_key=api_key
        )
        print("[INFO] RAG module initialized, Embedding model: {}".format(self.embedding_model_type))
        
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
            length_function=len
        )
        
        self.prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                """你是一个知识库助手。请根据以下提供的上下文信息回答用户问题。

上下文：
{context}

请基于以上上下文回答问题。如果上下文中没有相关信息，请明确说明。"""
            ),
            ("user", "{input}")
        ])
    
    def load_documents(self, file_paths):
        """加载并切分文档，按扩展名路由 loader（Day 11-12）。

        Args:
            file_paths: 文件路径列表；支持 txt / md / pdf / docx / csv / json / html。

        Returns:
            ``(ok: bool, summary: str)``。失败但部分成功时 ok=False，summary 列出错的文件。
        """
        documents: List[Document] = []
        errors: List[str] = []
        for file_path in file_paths:
            try:
                docs = DocumentLoaderRegistry.load(file_path)
                if docs:
                    documents.extend(docs)
            except Exception as e:
                msg = f"[ERROR] Failed to load {file_path}: {e}"
                print(msg)
                errors.append(msg)

        if not documents:
            return False, f"无有效文档加载（{len(errors)} 个失败）"

        split_docs = self.text_splitter.split_documents(documents)
        self.vectorstore = self._create_vectorstore(split_docs)

        self.retriever = self._create_retriever()

        self.rag_chain = (
            {"context": self.retriever, "input": RunnablePassthrough()}
            | self.prompt
            | self.model
            | StrOutputParser()
        )

        if errors:
            return True, f"部分加载 ({len(errors)} 失败): " + "; ".join(errors[:3])
        return True, f"已加载 {len(split_docs)} 个 chunk（来自 {len(file_paths)} 个文件）"

    def query(self, question):
        if not self.rag_chain:
            return "请先加载知识库文档"

        try:
            result = self.rag_chain.invoke(question)
            return result
        except Exception as e:
            return "查询失败: {}".format(str(e))

    def add_documents(self, file_paths):
        """增量加入文档（已存在 vectorstore 时使用）。"""
        if not self.vectorstore:
            return self.load_documents(file_paths)

        documents: List[Document] = []
        for file_path in file_paths:
            try:
                docs = DocumentLoaderRegistry.load(file_path)
                documents.extend(docs or [])
            except Exception as e:
                print("[ERROR] Failed to load {}: {}".format(file_path, e))

        if documents:
            split_docs = self.text_splitter.split_documents(documents)
            self.vectorstore.add_documents(split_docs)
            return True, f"已增量加入 {len(split_docs)} 个 chunk"

        return False, "无有效文档可加入"

    def _vectorstore_backend_id(self) -> str:
        """向量库后端 id。允许通过 RAGModule(vectorstore_backend=...) 切换。"""
        return getattr(self, "_vectorstore_backend", "chroma")

    def _create_vectorstore(self, documents):
        try:
            from plugins.rag_backends.registry import VectorStoreBackendRegistry
            vs = VectorStoreBackendRegistry.create(
                self._vectorstore_backend_id(),
                {"collection_name": "knowledge_base"},
            )
            return vs.from_documents(documents=documents, embedding=self.embeddings)
        except KeyError:
            pass
        # 兜底：原有 Chroma 实现
        return Chroma.from_documents(
            documents=documents,
            embedding=self.embeddings,
            collection_name="knowledge_base",
        )

    def _create_retriever(self):
        try:
            from plugins.rag_backends.registry import VectorStoreBackendRegistry
            vs = VectorStoreBackendRegistry.create(
                self._vectorstore_backend_id(), {}
            )
            return vs.as_retriever(self.vectorstore)
        except KeyError:
            return self.vectorstore.as_retriever(search_kwargs={"k": 3})

    def supported_formats(self) -> List[str]:
        """当前注册器支持的扩展名前缀（如 ``.pdf .docx``）。"""
        return [s.lstrip(".") for s in DocumentLoaderRegistry.supported_suffixes()]  # type: ignore[union-attr]  # noqa: E501
    
    def clear_knowledge_base(self):
        if self.vectorstore:
            self.vectorstore.delete_collection()
            self.vectorstore = None
            self.retriever = None
            self.rag_chain = None
            return True
        return False
