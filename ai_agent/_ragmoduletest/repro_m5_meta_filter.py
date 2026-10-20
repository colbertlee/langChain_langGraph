# -*- coding: utf-8 -*-
"""最小复现用例：vector_store.VectorStore.query(where=...) 元数据过滤缺陷

现象：query 传入 where 时抛 ValueError。验证：where=None 正常；where 触发异常；
修复方向（$and）在 chromadb 0.5 下可用。
使用 DeterministicEmbedding（零网络，隔离 where 逻辑本身）。
"""
import os, shutil, tempfile, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from vector_store import VectorStore, DeterministicEmbedding

tmp = tempfile.mkdtemp(prefix="repro_m5_")
print("chromadb:", __import__("chromadb").__version__)
try:
    vs = VectorStore(persist_dir=tmp, collection_name="reprocmeta", embedding=DeterministicEmbedding(dim=64))
    S = "s1"
    # 写入两个不同文件的 chunk
    vs.upsert_chunks(chunks=[{"text": "Python 由 Guido 于 1991 年发布。", "chunk_id": 0}],
                     session_id=S, file_id="py", file_name="python_intro.txt")
    vs.upsert_chunks(chunks=[{"text": "Java 由 James Gosling 于 1995 年发布。", "chunk_id": 0}],
                     session_id=S, file_id="java", file_name="java_intro.txt")

    # 1) where=None 正常
    r0 = vs.query(query_text="Python", session_id=S, top_k=2)
    print("\n[1] where=None -> OK, rows =", len(r0))

    # 2) 复现缺陷
    try:
        vs.query(query_text="Python", session_id=S, top_k=2, where={"file_name": "python_intro.txt"})
        print("[2] where={'file_name':...} -> NO ERROR (意外通过)")
        reproduced = False
    except Exception as e:
        print("[2] where={'file_name':...} -> 抛异常:", str(e).splitlines()[0])
        reproduced = True

    # 3) 修复方向：$and 显式结构在 chromadb 0.5 下可用
    import chromadb
    col = vs.collection
    res = col.query(query_embeddings=vs.embedding.embed_documents(["Python"])[0] and
                    col._client is not None and vs.embedding.embed_query("Python"),
                    n_results=2,
                    where={"$and": [{"session_id": S}, {"file_name": "python_intro.txt"}]},
                    include=["documents", "metadatas"])
    metas = (res.get("metadatas") or [[]])[0]
    print("[3] $and 修复写法 -> 命中文件:", sorted({m.get("file_name") for m in metas}), "(仅python_intro)")

    print("\n复现:", reproduced)
finally:
    shutil.rmtree(tmp, ignore_errors=True)