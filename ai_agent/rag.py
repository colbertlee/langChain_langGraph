"""
RAG 模块 - 兼容 LangChain 1.x

适配点：
- 不再使用 langchain.retrievers.EnsembleRetriever / ContextualCompressionRetriever
  （这些类在 LC 1.0 已迁出 langchain 包）
- 自实现轻量 EnsembleRetriever（向量 + BM25 RRF 融合）
- Rerank 用 sentence_transformers.CrossEncoder + 自定义 DocumentCompressor
"""
from typing import List, Sequence
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough

from config import OPENAI_API_KEY, EMBEDDING_API_KEY, EMBEDDING_MODEL_TYPE


# ===================== Embedding 工厂 =====================

def get_embedding_model(model_type="openai", api_key=None):
    key = api_key or EMBEDDING_API_KEY or OPENAI_API_KEY

    if model_type == "openai":
        print("[INFO] Using OpenAI text-embedding-3-small (1536 dimension)")
        return OpenAIEmbeddings(api_key=key)

    elif model_type == "minimax":
        try:
            from langchain_community.embeddings import MiniMaxEmbeddings
            print("[INFO] Using MiniMax embo-01 (1024 dimension)")
            return MiniMaxEmbeddings(mini_max_api_key=key, model_name="embo-01")
        except ImportError:
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)

    elif model_type == "zhipu":
        try:
            from langchain_community.embeddings import ZhipuAIEmbeddings
            print("[INFO] Using Zhipu embedding-2 (1024 dimension)")
            return ZhipuAIEmbeddings(
                api_key=key, model="embedding-2",
                zhipuai_api_base="https://open.bigmodel.cn/api/paas/v4/"
            )
        except ImportError:
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)

    elif model_type == "jina":
        try:
            from langchain_community.embeddings import JinaEmbeddings
            print("[INFO] Using Jina AI jina-embeddings-v3 (1024 dimension)")
            return JinaEmbeddings(jina_api_key=key, model_name="jina-embeddings-v3")
        except ImportError:
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)

    elif model_type == "ollama":
        try:
            from langchain_community.embeddings import OllamaEmbeddings
            # 默认模型名，可通过 OLLAMA_MODEL 环境变量覆盖
            import os
            ollama_model = os.environ.get("OLLAMA_MODEL", "nomic-embed-text")
            print("[INFO] Using Ollama local model: {}".format(ollama_model))
            return OllamaEmbeddings(model=ollama_model, base_url="http://localhost:11434")
        except ImportError:
            print("[WARN] Fallback to OpenAI Embedding")
            return OpenAIEmbeddings(api_key=key)

    elif model_type == "local":
        # 离线兜底：TF-IDF 向量化 + Chroma，零网络依赖
        print("[INFO] Using local TF-IDF embedding (offline, no API)")
        return TfidfEmbedding()

    else:
        print("[WARN] Unsupported model type: {}, using OpenAI".format(model_type))
        return OpenAIEmbeddings(api_key=key)


# ===================== 离线 TF-IDF Embedding =====================

import math
import re
from collections import Counter, defaultdict


def _tokenize(text: str) -> List[str]:
    """中英文混合分词：英文按词、中文按 1~2 字切"""
    text = text.lower()
    # 英文/数字
    en_tokens = re.findall(r"[a-z0-9]+", text)
    # 中文：单字 + 二元
    zh_chars = re.findall(r"[\u4e00-\u9fff]", text)
    zh_bigrams = ["".join(zh_chars[i:i + 2]) for i in range(len(zh_chars) - 1)]
    return en_tokens + zh_chars + zh_bigrams


class TfidfEmbedding:
    """
    离线 Embedding：训练时统计 IDF，推理时算 TF-IDF 稀疏向量。
    兼容 langchain Embeddings 接口：embed_documents / embed_query。

    优点：零网络、零额外依赖、可控、可解释
    缺点：没有语义泛化（同义词/句式变化召回差）
    """

    def __init__(self):
        self.vocab = {}
        self.idf = {}
        self.doc_count = 0

    def _fit(self, docs_tokens: List[List[str]]):
        self.doc_count = len(docs_tokens)
        df = defaultdict(int)
        for tokens in docs_tokens:
            for t in set(tokens):
                df[t] += 1
        # 排序建词表，保证维度稳定
        self.vocab = {t: i for i, t in enumerate(sorted(df.keys()))}
        self.idf = {t: math.log((1 + self.doc_count) / (1 + c)) + 1 for t, c in df.items()}

    def _vectorize(self, tokens: List[str]) -> List[float]:
        if not self.vocab:
            return []
        vec = [0.0] * len(self.vocab)
        tf = Counter(tokens)
        for t, c in tf.items():
            if t in self.vocab:
                vec[self.vocab[t]] = c * self.idf.get(t, 0.0)
        # L2 normalize
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        tokenized = [_tokenize(t) for t in texts]
        self._fit(tokenized)
        return [self._vectorize(t) for t in tokenized]

    def embed_query(self, text: str) -> List[float]:
        return self._vectorize(_tokenize(text))


# ===================== 自实现 BM25 Retriever（零依赖） =====================

class _SimpleBM25Retriever:
    """
    简化版 BM25 Retriever，替代 langchain_community.retrievers.BM25Retriever。
    接口与原版一致：from_documents(docs) / .invoke(query) / .k。

    算法：标准 BM25Okapi，k1=1.5, b=0.75
    """

    def __init__(self, documents=None, k1=1.5, b=0.75):
        self.documents = documents or []
        self.k1 = k1
        self.b = b
        self.k = 4  # 默认 top-k
        self._index_built = False

    @classmethod
    def from_documents(cls, documents):
        retriever = cls(documents=list(documents))
        retriever._build_index()
        return retriever

    def _build_index(self):
        self._tokenized_docs = [_tokenize(d.page_content) for d in self.documents]
        self._doc_lens = [len(t) for t in self._tokenized_docs]
        self._avg_doc_len = (sum(self._doc_lens) / len(self._doc_lens)) if self._doc_lens else 0
        # 文档频率
        df = defaultdict(int)
        for tokens in self._tokenized_docs:
            for t in set(tokens):
                df[t] += 1
        self._df = df
        self._n_docs = len(self.documents)
        self._index_built = True

    def _idf(self, term: str) -> float:
        df = self._df.get(term, 0)
        # BM25 IDF 公式
        import math
        return math.log((self._n_docs - df + 0.5) / (df + 0.5) + 1.0)

    def _score(self, query_tokens, doc_tokens, doc_len):
        score = 0.0
        tf = Counter(doc_tokens)
        for q in query_tokens:
            if q not in tf:
                continue
            f = tf[q]
            idf = self._idf(q)
            denom = f + self.k1 * (1 - self.b + self.b * doc_len / (self._avg_doc_len or 1))
            score += idf * (f * (self.k1 + 1)) / denom
        return score

    def invoke(self, query: str) -> List[Document]:
        if not self._index_built or not self.documents:
            return []
        query_tokens = _tokenize(query)
        scored = []
        for doc, tokens, dl in zip(self.documents, self._tokenized_docs, self._doc_lens):
            s = self._score(query_tokens, tokens, dl)
            if s > 0:
                scored.append((s, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[: self.k]]


# ===================== 轻量 RRF 融合检索器 =====================

class RRFFusionRetriever:
    """
    自实现 RRF（Reciprocal Rank Fusion）混合检索器

    final_score(d) = sum( w_i / (k + rank_i(d)) )

    不依赖 langchain.retrievers.EnsembleRetriever（LC 1.x 已删除）。
    兼容 Runnable 接口：invoke / ainvoke / stream。
    """

    def __init__(self, retrievers: List, weights: List[float] = None, rrf_k: int = 60):
        assert len(retrievers) > 0
        if weights is None:
            weights = [1.0 / len(retrievers)] * len(retrievers)
        assert len(weights) == len(retrievers)
        self.retrievers = retrievers
        self.weights = weights
        self.rrf_k = rrf_k

    def invoke(self, query: str, config=None, **kwargs) -> List[Document]:
        return self._fuse(query)

    async def ainvoke(self, query: str, config=None, **kwargs) -> List[Document]:
        return self._fuse(query)

    def _fuse(self, query: str) -> List[Document]:
        scores = {}
        docs_by_key = {}

        for retriever, weight in zip(self.retrievers, self.weights):
            try:
                results = retriever.invoke(query)
            except Exception as e:
                print("[WARN] Retriever {} failed: {}".format(type(retriever).__name__, e))
                continue

            for rank, doc in enumerate(results, start=1):
                cid = doc.metadata.get("chunk_id")
                key = ("cid", cid) if cid is not None else ("txt", doc.page_content[:200])
                if key not in scores:
                    scores[key] = 0.0
                    docs_by_key[key] = doc
                scores[key] += weight / (self.rrf_k + rank)

        sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        return [docs_by_key[k] for k in sorted_keys]


# ===================== 轻量 Cross-Encoder Rerank =====================

class CrossEncoderReranker:
    """
    自实现 Cross-Encoder Rerank 压缩器

    替代 langchain.retrievers.document_compressors.CrossEncoderReranker
    接口与 BaseDocumentCompressor 一致：compress_documents(documents, query)
    """

    def __init__(self, model_name: str = "BAAI/bge-reranker-base", top_n: int = 5, device: str = "cpu"):
        from sentence_transformers import CrossEncoder
        print("[INFO] Loading rerank model: {}".format(model_name))
        self.model = CrossEncoder(model_name, device=device)
        self.top_n = top_n

    def compress_documents(self, documents: Sequence[Document], query: str) -> List[Document]:
        if not documents:
            return []
        pairs = [[query, d.page_content] for d in documents]
        scores = self.model.predict(pairs)
        scored = sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)
        top = [d for d, _ in scored[: self.top_n]]
        return top


# ===================== Rerank 结果缓存 =====================

class RerankCache:
    """
    LRU + TTL 缓存，用于缓存 Cross-Encoder Rerank 的输入/输出对。
    命中条件：query 完全相同（归一化后）+ chunk 集合未变（用 docs hash 校验）。

    设计取舍：
    - 缓存粒度：缓存 (query → 排序后 chunk 列表)
    - chunk 列表变化（重索引后）自动失效：docs_hash 不一致则跳过缓存
    - 线程安全：Lock 保护；OrderedDict 维护 LRU
    """

    def __init__(self, max_size: int = 256, ttl_seconds: int = 600):
        from collections import OrderedDict
        from threading import Lock
        import time

        self._data = OrderedDict()
        self._lock = Lock()
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._time = time.time

        # 统计
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _normalize(q: str) -> str:
        return (q or "").strip().lower()

    @staticmethod
    def _docs_hash(documents) -> str:
        """用 chunk_id 列表做指纹，KB 重索引后自动失效"""
        import hashlib
        ids = sorted(d.metadata.get("chunk_id", 0) for d in documents)
        return hashlib.md5(str(ids).encode("utf-8")).hexdigest()

    def get(self, query: str, docs_hash: str):
        key = (self._normalize(query), docs_hash)
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            ts, result = entry
            if self._time() - ts > self.ttl:
                # 过期
                self._data.pop(key, None)
                self.misses += 1
                return None
            # LRU：移到末尾
            self._data.move_to_end(key)
            self.hits += 1
            return result

    def set(self, query: str, docs_hash: str, result):
        key = (self._normalize(query), docs_hash)
        with self._lock:
            self._data[key] = (self._time(), result)
            self._data.move_to_end(key)
            # 淘汰最旧的
            while len(self._data) > self.max_size:
                self._data.popitem(last=False)

    def clear(self):
        with self._lock:
            self._data.clear()

    def stats(self):
        total = self.hits + self.misses
        rate = (self.hits / total) if total else 0.0
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": rate,
            "size": len(self._data),
            "max_size": self.max_size,
            "ttl": self.ttl,
        }


class CachedRerankWrapper:
    """包装 CrossEncoderReranker，加一层缓存"""

    def __init__(self, reranker, cache: RerankCache = None):
        self.reranker = reranker
        self.cache = cache or RerankCache()
        self.top_n = reranker.top_n

    def compress_documents(self, documents, query: str):
        if not documents:
            return []
        docs_hash = RerankCache._docs_hash(documents)
        cached = self.cache.get(query, docs_hash)
        if cached is not None:
            return cached
        result = self.reranker.compress_documents(documents, query)
        self.cache.set(query, docs_hash, result)
        return result


# ===================== RAG 模块 =====================

class RAGModule:
    def __init__(self, model, api_key=None, embedding_model_type=None,
                 use_cache: bool = True, cache_size: int = 256, cache_ttl: int = 600):
        self.model = model
        self.api_key = api_key
        self.embedding_model_type = embedding_model_type or EMBEDDING_MODEL_TYPE or "openai"
        self.vectorstore = None
        self.retriever = None
        self.rag_chain = None
        self.all_split_docs = []
        # Rerank 缓存
        self.use_cache = use_cache
        self.rerank_cache = RerankCache(max_size=cache_size, ttl_seconds=cache_ttl)

        # 记录具体 embedding 模型名（用于 collection 名去重）
        # ollama / jina 等可能有多个候选
        import os as _os
        self.embedding_model_name = _os.environ.get(
            "OLLAMA_MODEL", self.embedding_model_type
        )

        self.embeddings = get_embedding_model(
            model_type=self.embedding_model_type,
            api_key=api_key
        )
        print("[INFO] RAG module initialized, Embedding model: {}".format(self.embedding_model_type))

        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=400,
            chunk_overlap=80,
            length_function=len,
            separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""]
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

    # ---------- 切分 ----------

    def _split_documents(self, documents):
        split_docs = self.text_splitter.split_documents(documents)
        for i, d in enumerate(split_docs):
            d.metadata["chunk_id"] = i
        return split_docs

    # ---------- 构建混合 + Rerank 检索器 ----------

    def _build_retriever(self, split_docs, use_rerank: bool = True, rerank_top_n: int = 5):
        """
        构建检索器，可插拔开关：
        - use_rerank=True:  RRF 融合 + Cross-Encoder Rerank
        - use_rerank=False: 仅 RRF 融合（便于 A/B 对比）
        """
        # 1) 向量召回
        vector_retriever = self.vectorstore.as_retriever(
            search_type="similarity",
            search_kwargs={"k": 20}
        )
        # 2) BM25 召回（自实现，零依赖）
        bm25_retriever = _SimpleBM25Retriever.from_documents(split_docs)
        bm25_retriever.k = 20

        # 3) RRF 融合（向量 0.5 + BM25 0.5，平衡混合检索）
        # 依据 sweep 实测：v0.5_b0.5 + Rerank recall=96.67%, MRR=0.8944
        # 详细对比见 evals/runs/rag_sweep_v3/sweep_report.md
        ensemble = RRFFusionRetriever(
            retrievers=[vector_retriever, bm25_retriever],
            weights=[0.5, 0.5]
        )

        if not use_rerank:
            print("[INFO] Retriever: Hybrid (Vector+BM25) only, no Rerank")
            return ensemble

        # 4) Rerank 压缩：包一层，调用方式一致
        raw_reranker = CrossEncoderReranker(
            model_name="BAAI/bge-reranker-base",
            top_n=rerank_top_n,
            device="cpu"
        )
        # 加缓存包装
        if self.use_cache:
            self._reranker = CachedRerankWrapper(raw_reranker, self.rerank_cache)
            print("[INFO] Retriever: Hybrid + Rerank + Cache (size={}, ttl={}s)".format(
                self.rerank_cache.max_size, self.rerank_cache.ttl))
        else:
            self._reranker = raw_reranker
            print("[INFO] Retriever: Hybrid + Rerank (no cache)")

        # 把 compressor 包装成 langchain Runnable，让 LCEL `{"context": retriever}` 能识别
        # RunnableLambda 接收单参函数并提供 invoke/ainvoke/batch/stream 等接口
        from langchain_core.runnables import RunnableLambda

        def _retrieve_and_compress(query: str):
            docs = ensemble.invoke(query)
            return self._reranker.compress_documents(docs, query)

        return RunnableLambda(_retrieve_and_compress)

    # ---------- Query 改写 ----------

    def _rewrite_query(self, question: str) -> str:
        if not self.model:
            return question
        try:
            rewrite_prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "你是检索查询改写助手。请把用户问题改写为更适合在知识库中检索的关键词形式。"
                 "保持原意，补全省略成分，输出 1 条改写后的查询，不要回答问题本身。"),
                ("user", "{q}")
            ])
            chain = rewrite_prompt | self.model | StrOutputParser()
            rewritten = chain.invoke({"q": question}).strip()
            rewritten = rewritten.split("\n")[0].strip()
            if rewritten:
                print("[INFO] Query rewrite: '{}' -> '{}'".format(question, rewritten))
                return rewritten
            return question
        except Exception as e:
            print("[WARN] Query rewrite failed: {}, use original".format(e))
            return question

    # ---------- 文档加载 ----------

    def load_documents(self, file_paths, use_rerank: bool = True, rerank_top_n: int = 5):
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

        split_docs = self._split_documents(documents)
        self.all_split_docs = split_docs

        # collection 名带 embedding 模型名，避免不同维度互相冲突
        collection_name = "kb_{}".format(
            self.embedding_model_name.replace(":", "_").replace("-", "_").replace(".", "_")
        )

        self.vectorstore = Chroma.from_documents(
            documents=split_docs,
            embedding=self.embeddings,
            collection_name=collection_name
        )

        self.retriever = self._build_retriever(split_docs, use_rerank=use_rerank, rerank_top_n=rerank_top_n)

        # 重索引后清缓存（旧 chunk_id 已失效）
        if self.use_cache:
            self.rerank_cache.clear()

        # 仅在提供了 model 时才构建 rag_chain（评估模式 model=None 时跳过）
        if self.model is not None:
            self.rag_chain = (
                {"context": self.retriever, "input": RunnablePassthrough()}
                | self.prompt
                | self.model
                | StrOutputParser()
            )

        return True

    def add_documents(self, file_paths, use_rerank: bool = True, rerank_top_n: int = 5):
        if not self.vectorstore:
            return self.load_documents(file_paths, use_rerank=use_rerank, rerank_top_n=rerank_top_n)

        documents = []
        for file_path in file_paths:
            try:
                loader = TextLoader(file_path, encoding="utf-8")
                docs = loader.load()
                documents.extend(docs)
            except Exception as e:
                print("[ERROR] Failed to load document {}: {}".format(file_path, e))

        if documents:
            split_docs = self._split_documents(documents)
            self.vectorstore.add_documents(split_docs)
            self.all_split_docs.extend(split_docs)
            self.retriever = self._build_retriever(
                self.all_split_docs, use_rerank=use_rerank, rerank_top_n=rerank_top_n
            )
            if self.use_cache:
                self.rerank_cache.clear()
            if self.model is not None:
                self.rag_chain = (
                    {"context": self.retriever, "input": RunnablePassthrough()}
                    | self.prompt
                    | self.model
                    | StrOutputParser()
                )
            return True

        return False

    # ---------- 查询 ----------

    def query(self, question):
        if not self.rag_chain:
            return "请先加载知识库文档"

        try:
            rewritten = self._rewrite_query(question)
            result = self.rag_chain.invoke(rewritten)
            return result
        except Exception as e:
            return "查询失败: {}".format(str(e))

    def retrieve(self, question, top_k=5):
        """仅做检索，返回 chunk 列表，便于做召回率评估"""
        if not self.retriever:
            return []
        rewritten = self._rewrite_query(question)
        docs = self.retriever.invoke(rewritten)
        return docs[:top_k]

    def cache_stats(self):
        """查看 Rerank 缓存统计"""
        if not self.use_cache:
            return {"enabled": False}
        s = self.rerank_cache.stats()
        s["enabled"] = True
        return s

    def clear_knowledge_base(self):
        if self.vectorstore:
            self.vectorstore.delete_collection()
            self.vectorstore = None
            self.retriever = None
            self.rag_chain = None
            self.all_split_docs = []
            if self.use_cache:
                self.rerank_cache.clear()
            return True
        return False