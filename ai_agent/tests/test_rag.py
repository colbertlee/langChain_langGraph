"""rag.py 单元测试（mock Chroma / OpenAIEmbeddings）。"""
import os
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def mock_model():
    """Mock ChatModel。"""
    return MagicMock()


@pytest.fixture
def rag(mock_model):
    """创建 RAGModule 实例，mock 掉所有外部依赖。"""
    with patch("rag.OpenAIEmbeddings") as mock_emb, \
         patch("rag.Chroma") as mock_chroma, \
         patch("rag.TextLoader") as mock_loader, \
         patch("rag.RecursiveCharacterTextSplitter") as mock_splitter:
        # 默认 embedding model
        mock_emb.return_value = MagicMock()

        # 默认 splitter
        mock_splitter_instance = MagicMock()
        mock_splitter_instance.split_documents.return_value = ["doc1", "doc2"]
        mock_splitter.return_value = mock_splitter_instance

        # 默认 Chroma
        mock_vs = MagicMock()
        mock_vs.as_retriever.return_value = MagicMock()
        mock_chroma.from_documents.return_value = mock_vs

        # TextLoader
        mock_loader.return_value.load.return_value = [MagicMock(page_content="hello")]

        from rag import RAGModule
        module = RAGModule(mock_model, api_key="sk-fake")

        yield module, {
            "model": mock_model,
            "embeddings": mock_emb,
            "chroma": mock_chroma,
            "loader": mock_loader,
            "splitter": mock_splitter,
            "vectorstore": mock_vs,
        }


class TestInit:

    def test_init_with_model(self, mock_model):
        with patch("rag.OpenAIEmbeddings"), patch("rag.RecursiveCharacterTextSplitter"):
            from rag import RAGModule
            module = RAGModule(mock_model, api_key="sk-test")
            assert module.model is mock_model
            assert module.api_key == "sk-test"
            assert module.embedding_model_type is not None

    def test_init_default_embedding_type(self, mock_model):
        with patch("rag.OpenAIEmbeddings"), patch("rag.RecursiveCharacterTextSplitter"):
            from rag import RAGModule
            module = RAGModule(mock_model, api_key="sk-test")
            assert module.embedding_model_type in ("openai", "zhipu", "minimax", "jina", "ollama")

    def test_init_creates_text_splitter(self, mock_model):
        with patch("rag.OpenAIEmbeddings"), patch("rag.RecursiveCharacterTextSplitter") as mock_split:
            from rag import RAGModule
            module = RAGModule(mock_model, api_key="sk-test")
            # 验证 text_splitter 被创建（参数正确）
            mock_split.assert_called_once()
            call_args = mock_split.call_args
            # chunk_size, chunk_overlap, length_function
            assert "chunk_size" in call_args.kwargs or len(call_args.args) >= 1

    def test_init_creates_prompt(self, mock_model):
        with patch("rag.OpenAIEmbeddings"), patch("rag.RecursiveCharacterTextSplitter"):
            from rag import RAGModule
            module = RAGModule(mock_model, api_key="sk-test")
            assert module.prompt is not None

    def test_init_state_attributes(self, mock_model):
        with patch("rag.OpenAIEmbeddings"), patch("rag.RecursiveCharacterTextSplitter"):
            from rag import RAGModule
            module = RAGModule(mock_model, api_key="sk-test")
            assert module.vectorstore is None
            assert module.retriever is None
            assert module.rag_chain is None


class TestEmbeddingModel:

    def test_get_embedding_openai(self):
        from rag import get_embedding_model
        with patch("rag.OpenAIEmbeddings") as mock_emb:
            mock_emb.return_value = MagicMock()
            result = get_embedding_model("openai", api_key="sk-test")
            assert result is not None
            mock_emb.assert_called_once_with(api_key="sk-test")

    def test_get_embedding_ollama(self):
        from rag import get_embedding_model
        with patch("rag.OpenAIEmbeddings") as mock_emb, \
             patch("langchain_community.embeddings.OllamaEmbeddings", create=True) as mock_ollama:
            mock_ollama.return_value = MagicMock()
            result = get_embedding_model("ollama")
            assert result is not None

    def test_get_embedding_unknown_falls_back(self):
        from rag import get_embedding_model
        with patch("rag.OpenAIEmbeddings") as mock_emb:
            mock_emb.return_value = MagicMock()
            result = get_embedding_model("unknown_type_xyz", api_key="sk-test")
            # 未知类型应 fallback 到 OpenAI
            mock_emb.assert_called_once()


class TestLoadDocuments:

    def test_load_documents_success(self, rag):
        module, mocks = rag
        result = module.load_documents(["doc1.txt", "doc2.txt"])
        assert result is True
        # Chroma.from_documents 被调用
        mocks["chroma"].from_documents.assert_called_once()

    def test_load_documents_empty(self, rag):
        module, mocks = rag
        # 模拟 loader 全部失败
        mocks["loader"].return_value.load.side_effect = Exception("load failed")
        result = module.load_documents(["bad.txt"])
        assert result is False

    def test_load_documents_creates_retriever(self, rag):
        module, mocks = rag
        module.load_documents(["doc.txt"])
        # vectorstore.as_retriever 应被调用
        mocks["vectorstore"].as_retriever.assert_called_once()
        # k=3
        call_args = mocks["vectorstore"].as_retriever.call_args
        assert call_args.kwargs.get("search_kwargs", {}).get("k") == 3

    def test_load_documents_builds_rag_chain(self, rag):
        module, mocks = rag
        module.load_documents(["doc.txt"])
        # rag_chain 应被创建
        assert module.rag_chain is not None


class TestQuery:

    def test_query_without_load(self, rag):
        module, mocks = rag
        # 没加载文档直接查询
        result = module.query("test question")
        assert "请先加载" in result

    def test_query_after_load(self, rag):
        module, mocks = rag
        module.load_documents(["doc.txt"])
        # mock rag_chain.invoke
        module.rag_chain = MagicMock()
        module.rag_chain.invoke.return_value = "Answer from RAG"
        result = module.query("What is X?")
        assert result == "Answer from RAG"

    def test_query_exception(self, rag):
        module, mocks = rag
        module.load_documents(["doc.txt"])
        module.rag_chain = MagicMock()
        module.rag_chain.invoke.side_effect = Exception("LLM down")
        result = module.query("test")
        assert "查询失败" in result or "Error" in result or "down" in result


class TestAddDocuments:

    def test_add_documents_without_vectorstore(self, rag):
        module, mocks = rag
        # 没加载过 → 调用 load_documents
        result = module.add_documents(["new_doc.txt"])
        # load_documents 返回 True
        assert result is True

    def test_add_documents_to_existing(self, rag):
        module, mocks = rag
        module.load_documents(["initial.txt"])
        # 现在 vectorstore 不为 None
        result = module.add_documents(["new.txt"])
        assert result is True
        # vectorstore.add_documents 被调用
        mocks["vectorstore"].add_documents.assert_called()

    def test_add_documents_empty(self, rag):
        module, mocks = rag
        module.load_documents(["initial.txt"])
        # loader 抛错 → 空列表 → return False
        mocks["loader"].return_value.load.side_effect = Exception("fail")
        result = module.add_documents(["bad.txt"])
        assert result is False


class TestClear:

    def test_clear_with_vectorstore(self, rag):
        module, mocks = rag
        module.load_documents(["doc.txt"])
        result = module.clear_knowledge_base()
        assert result is True
        # vectorstore.delete_collection 被调用
        mocks["vectorstore"].delete_collection.assert_called_once()
        assert module.vectorstore is None
        assert module.retriever is None
        assert module.rag_chain is None

    def test_clear_without_vectorstore(self, rag):
        module, mocks = rag
        # 没加载文档直接 clear
        result = module.clear_knowledge_base()
        assert result is False