from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from config import OPENAI_API_KEY, EMBEDDING_API_KEY, EMBEDDING_MODEL_TYPE

def get_embedding_model(model_type="openai", api_key=None):
    key = api_key or EMBEDDING_API_KEY or OPENAI_API_KEY
    if model_type == "zhipu":
        from langchain_community.embeddings import ZhipuAIEmbeddings
        return ZhipuAIEmbeddings(api_key=key, model="embedding-2", zhipuai_api_base="https://open.bigmodel.cn/api/paas/v4/")
    return OpenAIEmbeddings(api_key=key)

class RAGModule:
    def __init__(self, model, api_key=None, embedding_model_type=None):
        self.model = model
        self.embeddings = get_embedding_model(embedding_model_type or EMBEDDING_MODEL_TYPE, api_key)
        self.text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
        self.prompt = ChatPromptTemplate.from_messages([("system", "Context: {context}"), ("user", "{input}")])
    
    def load_documents(self, file_paths):
        documents = []
        for path in file_paths:
            try: documents.extend(TextLoader(path, encoding="utf-8").load())
            except: pass
        if not documents: return False
        self.vectorstore = Chroma.from_documents(
            self.text_splitter.split_documents(documents), self.embeddings, collection_name="knowledge_base")
        self.retriever = self.vectorstore.as_retriever(search_kwargs={"k": 3})
        self.rag_chain = ({"context": self.retriever, "input": RunnablePassthrough()}
                         | self.prompt | self.model | StrOutputParser())
        return True
    
    def query(self, question):
        return self.rag_chain.invoke(question) if self.rag_chain else "Load KB first"