# -*- coding: utf-8 -*-
"""模块5：检索（向量 + BM25 + RRF 融合 + 元数据过滤）。

后端：本机 Ollama bge-m3 向量 + 自实现 BM25 + RRF(0.5/0.5)。
Rerank：KB 为小文档(<50 chunks)，系统按 _auto_disable_rerank 自动关闭
        CrossEncoder（该启发式本身纳入评测），故此处验证 RRF 混合检索路径。
"""
import os
import shutil
import tempfile

from langchain_core.documents import Document
from common import ModuleReport, KB_FILES, read_raw_text
import common
from eval_set import RETRIEVAL_CASES, ABSENT_CASES


def main():
    from rag import _SimpleBM25Retriever, RRFFusionRetriever
    from rag_service import split_text
    from vector_store import VectorStore, OllamaEmbedding

    E = OllamaEmbedding(model="bge-m3", base_url="http://localhost:11434", timeout=300)
    tmp = tempfile.mkdtemp(prefix="ragmoduletest_m5_")
    rep = ModuleReport("模块5 检索（向量+BM25+RRF）")
    try:
        vs = VectorStore(persist_dir=tmp, collection_name="m5retrieval", embedding=E)
        SESSION = "m5"

        # ---- 构建语料：全库切片，全局唯一 chunk_id ----
        corpus = []      # Document
        gid = 0
        per_file_chunks = {}  # fname -> [chunk dict]
        for fname in KB_FILES:
            raw = read_raw_text(fname)
            from rag import clean_text
            cleaned = clean_text(raw)
            chunks = split_text(cleaned, chunk_size=500, chunk_overlap=80)
            flist = []
            for c in chunks:
                doc = Document(
                    page_content=c["text"],
                    metadata={"chunk_id": gid, "file_name": fname, "source": fname}
                )
                corpus.append(doc)
                flist.append({"text": c["text"], "chunk_id": gid})
                gid += 1
            per_file_chunks[fname] = flist

        # 向量入库（每文件一袋，携带全局 gid 作为 chunk_id + file_name 元数据）
        for fname, flist in per_file_chunks.items():
            vs.upsert_chunks(chunks=flist, session_id=SESSION,
                             file_id=os.path.splitext(fname)[0], file_name=fname)

        # ---- 向量 retriever（包装 vs.query → Document，保持同样 metadata） ----
        def vec_invoke(query):
            res = vs.query(query_text=query, session_id=SESSION, top_k=20, min_score=0.0)
            docs = []
            for r in res:
                docs.append(Document(
                    page_content=r["text"],
                    metadata={"chunk_id": r["chunk_id"], "file_name": r["file_name"],
                              "source": r["file_name"]}
                ))
            return docs

        class VecRet:
            k = 20
            def invoke(self, q, *a, **k): return vec_invoke(q)

        bm25 = _SimpleBM25Retriever.from_documents(corpus)
        bm25.k = 20
        rrf = RRFFusionRetriever(retrievers=[VecRet(), bm25], weights=[0.5, 0.5], rrf_k=60)

        # ---- Recall@5 评估 ----
        def relevant(doc, case):
            return doc.metadata.get("file_name") == case["file"] and \
                   any(t in doc.page_content for t in case["src_terms"])

        hits = 0
        n = len(RETRIEVAL_CASES)
        noise_lines = []
        for case in RETRIEVAL_CASES:
            top = rrf.invoke(case["query"])[:5]
            hit = any(relevant(d, case) for d in top)
            hits += int(hit)
            if not hit:
                got_files = {d.metadata.get("file_name") for d in top}
                noise_lines.append(f"  miss[{case['file']}] q={case['query'][:20]}... top文件={got_files}")
        recall5 = hits / n if n else 0.0
        ok_recall = recall5 >= 0.95
        rep.add("Recall@5（评估集）",
                f"Recall@5 ≥ 0.95", f"hits={hits}/{n} recall@5={recall5:.4f}",
                ok_recall)
        if not ok_recall:
            rep.defect("Recall@5 未达 0.95；未命中项：\n" + "\n".join(noise_lines))

        # ---- 假阳性检视：文档不存在的问题（观察噪声） ----
        fp_report = []
        for c in ABSENT_CASES:
            top = rrf.invoke(c["query"])[:5]
            files = [(d.metadata.get("file_name"), round(float_attr_score(d), 3))
                     for d in top]
            fp_report.append(f"  q={c['query'][:24]}... top文件与文件序号={[f[0] for f in files]}")
        rep.add("假阳性检视（absent 问题观察）",
                "召回可溯源；噪声待定性", "7 条 absent 查询的召回文件见缺陷区下方说明",
                True)  # 信息性；真正拒答在模块6
        rep.note("absent 查询仍会召回低相关片段（正常现象，拒答由模块6负责）:\n"
                 + "\n".join(fp_report))

        # ---- 元数据过滤：按文件名过滤检索范围 ----
        # 被测：vector_store.query(where=...) 的按文件过滤。（注意：chromadb 0.5
        # 要求 where 为单一操作符或 $and；模块把 session_id 与 where 平铺 dict.update，
        # 会产出双键扁平字典 → 预期可能抛 ValueError，此处捕获并如实记录。）
        filter_error = None
        py_chunks = [c for c in per_file_chunks["python_intro.txt"] if c["text"].strip()]
        try:
            filtered = vs.query(query_text="Python 由谁发布", session_id=SESSION,
                                top_k=5, where={"file_name": "python_intro.txt"})
            all_py = filtered and all(r["file_name"] == "python_intro.txt" for r in filtered)
            unfiltered = vs.query(query_text="如何做家常菜", session_id=SESSION, top_k=5)
            cross_file = any(r["file_name"] != "python_intro.txt" for r in unfiltered)
            ok_filter = all_py and cross_file
            rep.add("按文件名过滤检索范围",
                    "过滤后仅返回该文件；未过滤可跨文件",
                    f"过滤后全为python_intro={all_py}(返回{len(filtered)}条), "
                    f"未过滤含他文件={cross_file}", ok_filter)
            if not ok_filter:
                rep.defect("元数据过滤失效：where={'file_name':..} 未限定范围")
        except Exception as e:
            filter_error = str(e).splitlines()[0]
            rep.add("按文件名过滤检索范围", "过滤应仅返回该文件",
                    f"抛出异常: {filter_error}", False)
            rep.defect("缺陷: 元数据过滤触发异常 "
                       f"({filter_error}). 根因: vector_store.query 将 "
                       "session_id 与 where 用 dict.update 平铺合并而非 $and。"
                       "修复建议: where 组装改为 "
                       "{'$and': [{'session_id': session_id}, {'file_name': ...}]}")

        # ---- Rerank 自动关闭启发式评测 ----
        from rag import RAGModule
        try:
            heuristic = RAGModule._auto_disable_rerank(corpus, True, min_chunks=50)
            rep.add("Rerank 自动关闭启发式(小文档)",
                    "chunk数<50 应返回关闭(False)", f"_auto_disable_rerank(corpus=trueto50>)={heuristic}",
                    heuristic is False)
        except Exception as e:
            rep.add("Rerank 自动关闭启发式(小文档)", "小文档应关闭Rerank", f"异常{e}", False)

        passed = rep.render()
        print(f"模块5 通过 {rep.passed_total}/{rep.total} -> all_pass={rep.all_pass}")
        return 0 if rep.all_pass else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def float_attr_score(d):
    return getattr(d, "score", 0.0)


if __name__ == "__main__":
    raise SystemExit(main())