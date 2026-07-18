from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from config import OPENAI_API_KEY, EMBEDDING_API_KEY, EMBEDDING_MODEL_TYPE


def get_embedding_model(model_type="openai", api_key=None):
    """
    获取 Embedding 模型，支持多种模型
    
    Args:
        model_type: 模型类型 (openai/minimax/zhipu/jina/ollama)
        api_key: API Key
    
    Returns:
        Embedding 实例
    """
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


class RAGModule:
    def __init__(self, model, api_key=None, embedding_model_type=None):
        self.model = model
        self.api_key = api_key
        # 支持动态指定模型类型，或使用配置文件中的默认类型
        self.embedding_model_type = embedding_model_type or EMBEDDING_MODEL_TYPE or "openai"
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
        documents = []
        for file_path in file_paths:
            try:
                loader = TextLoader(file_path, encoding="utf-8")
                docs = loader.load()
                documents.extend(docs)
            except Exception as e:
                print("[ERROR] Failed to load document {}: {}".format(file_path, e))
        
        if not documents:
            return False
        
        split_docs = self.text_splitter.split_documents(documents)
        self.vectorstore = Chroma.from_documents(
            documents=split_docs,
            embedding=self.embeddings,
            collection_name="knowledge_base"
        )
        
        self.retriever = self.vectorstore.as_retriever(
            search_kwargs={"k": 3}
        )
        
        self.rag_chain = (
            {"context": self.retriever, "input": RunnablePassthrough()}
            | self.prompt
            | self.model
            | StrOutputParser()
        )
        
        return True
    
    def query(self, question):
        if not self.rag_chain:
            return "请先加载知识库文档"
        
        try:
            result = self.rag_chain.invoke(question)
            return result
        except Exception as e:
            return "查询失败: {}".format(str(e))
    
    def add_documents(self, file_paths):
        if not self.vectorstore:
            return self.load_documents(file_paths)
        
        documents = []
        for file_path in file_paths:
            try:
                loader = TextLoader(file_path, encoding="utf-8")
                docs = loader.load()
                documents.extend(docs)
            except Exception as e:
                print("[ERROR] Failed to load document {}: {}".format(file_path, e))
        
        if documents:
            split_docs = self.text_splitter.split_documents(documents)
            self.vectorstore.add_documents(split_docs)
            return True
        
        return False
    
    def clear_knowledge_base(self):
        if self.vectorstore:
            self.vectorstore.delete_collection()
            self.vectorstore = None
            self.retriever = None
            self.rag_chain = None
            return True
        return False
