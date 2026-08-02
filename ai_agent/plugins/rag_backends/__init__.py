"""RAG 后端插件集合。

提供 EmbeddingBackend / VectorStoreBackend 两类插件入口。
PluginManager 通过 ``plugins.rag_backends.openai_embedding`` /
``plugins.rag_backends.chroma_store`` 等 ``entry_point`` 加载。
"""