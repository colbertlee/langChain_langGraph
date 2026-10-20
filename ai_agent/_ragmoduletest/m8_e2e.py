# -*- coding: utf-8 -*-
"""模块8：整体系统端到端测试 —— 完整全链路。
链路：文档解析(file_parser) → 文本预处理(clean_text) → Chunk切片(split_text)
     → 向量化入库(VectorStore+bge-m3) → 多路检索(向量+BM25+RRF, 小文档按
       _auto_disable_rerank 自动关闭 Rerank) → LLM答案生成(qwen3.5:4b) → Self-Check。
后端：本机 Ollama bge-m3(向量) + qwen3.5:4b(生成)。
测试素材仅来自 knowledge_base/*.txt（冲突/多档用例使用由KB文本衍生的合成fixture，
已标注 synthetic，不引入外部知识库）。
"""
import os
import shutil
import tempfile

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

import common
from common import ModuleReport, OllamaChat, KB_FILES, read_raw_text, kb_path, KB_DIR


def main():
    from file_parser import parse_file
    from rag import clean_text, _SimpleBM25Retriever, RRFFusionRetriever, \
        _facts_grounded, RAGModule
    from rag_service import split_text
    from vector_store import VectorStore, OllamaEmbedding

    rep = ModuleReport("模块8 整体系统端到端")
    tmp = tempfile.mkdtemp(prefix="ragmoduletest_m8_")
    E = OllamaEmbedding(model="bge-m3", base_url="http://localhost:11434", timeout=300)
    LLM = OllamaChat(model="qwen3.5:4b", base_url="http://localhost:11434", temperature=0.1)

    PROMPT = ChatPromptTemplate.from_messages([
        ("system",
         """你是文档问答助手。必须严格遵守下面规则：
1. 只允许使用【参考文档片段】中的信息回答问题；禁止使用你自身知识库的任何内容。
2. 如果【参考文档片段】中没有任何片段与问题相关，必须回复："文档未找到相关内容"，禁止编造、禁止猜测。
3. 回答需简洁；若引用了片段，请在对应句子末尾用 [n] 标注来源编号（例如 [1]）。
4. 多个片段信息冲突时，以编号最小的片段为准，并简短说明冲突。

【参考文档片段】
{context}"""),
        ("user", "{input}"),
    ])

    def format_docs(docs):
        lines = []
        for i, d in enumerate(docs, start=1):
            content = (d.page_content if hasattr(d, "page_content") else d.get("text") or "") or ""
            content = content.strip()
            if content:
                lines.append(f"[{i}] {content}")
        return "\n\n".join(lines) if lines else "（无相关片段）"

    try:
        SESSION = "m8e2e"

        # ============ 1) 文档解析 + 2) 预处理 + 3) 切片 ============
        corpus = []
        gid = 0
        for fname in KB_FILES:
            p = parse_file(kb_path(fname), filename=fname)
            raw = p.text if p else read_raw_text(fname)
            cleaned = clean_text(raw)
            chunks = split_text(cleaned, chunk_size=500, chunk_overlap=80)
            for c in chunks:
                corpus.append(Document(
                    page_content=c["text"],
                    metadata={"chunk_id": gid, "file_name": fname, "source": fname}))
                gid += 1

        # ---- 合成 fixture A：与 python_intro 相冲突的"版本"文件（synthetic）----
        conflict_fname = "__synthetic_conflict.txt"
        py_v12 = clean_text(read_raw_text("python_intro.txt"))
        conflict_text = py_v12.replace("当前稳定版本是 Python 3.12",
                                       "当前稳定版本是 Python 3.7（注意：与官方文档冲突）")
        cchunks = split_text(conflict_text, chunk_size=500, chunk_overlap=80)
        for c in cchunks:
            corpus.append(Document(
                page_content=c["text"],
                metadata={"chunk_id": gid, "file_name": conflict_fname,
                          "source": conflict_fname}))
            gid += 1

        # ---- 全量入库（含合成冲突档）----
        vs = VectorStore(persist_dir=tmp, collection_name="m8e2e", embedding=E)
        for fname in KB_FILES + [conflict_fname]:
            flist = [{"text": c.page_content,
                      "chunk_id": c.metadata["chunk_id"]}
                     for c in corpus if c.metadata["file_name"] == fname]
            if flist:
                vs.upsert_chunks(chunks=flist, session_id=SESSION,
                                 file_id=os.path.splitext(fname)[0], file_name=fname)

        # ============ 多路检索（向量+BM25+RRF） ============
        def vec_invoke(query):
            res = vs.query(query_text=query, session_id=SESSION, top_k=20, min_score=0.0)
            return [Document(page_content=r["text"],
                             metadata={"chunk_id": r["chunk_id"],
                                       "file_name": r["file_name"],
                                       "source": r["file_name"]}) for r in res]

        class VecRet:
            k = 20
            def invoke(self, q, *a, **k): return vec_invoke(q)

        bm25 = _SimpleBM25Retriever.from_documents(corpus)
        bm25.k = 20
        rrf = RRFFusionRetriever(retrievers=[VecRet(), bm25], weights=[0.5, 0.5], rrf_k=60)
        use_rerank = RAGModule._auto_disable_rerank(corpus, True, min_chunks=50)
        rep.note(f"Rerank开关: use_rerank={use_rerank}（小文档自动关闭，混合检索=向量+BM25+RRF）")

        def retrieve(query, top_k=6):
            return rrf.invoke(query)[:top_k]

        def build_answer(query, docs):
            chain = PROMPT | LLM | StrOutputParser()
            return chain.invoke({"context": format_docs(docs), "input": query})

        def run(query, top_k=6):
            docs = retrieve(query, top_k=top_k)
            raw = build_answer(query, docs)          # LLM 原始输出
            chk = _facts_grounded(raw, docs)         # Self-Check 判定
            final = raw
            if chk["verdict"] == "block" and not any(m in raw for m in
                    ("文档未找到相关内容", "未找到相关信息", "无法回答", "不能回答")):
                final = "文档未找到相关内容（Self-Check 拦截）"
            return docs, raw, final, chk

        def files_of(docs):
            return sorted({d.metadata.get("file_name") for d in docs if d.metadata})

        # ============ 用例执行 ============
        cases = [
            # T8-01 单点事实
            dict(cid="T8-01", q="Python 是由谁、在哪一年发布的？",
                 expected="命中python_intro, 原始答含Guido/1991, Self-Check不误拦",
                 judge=lambda a, files, chk: ("Guido" in a and "1991" in a)),
            # T8-02 跨段综合
            dict(cid="T8-02", q="Python 有哪些主要特点和应用领域？",
                 expected="综合python特点与应用字段, 含简单易学等与Django/TensorFlow等",
                 judge=lambda a, files, chk: any(k in a for k in
                     ["简单易学", "面向对象", "动态类型"]) and any(k in a for k in
                     ["Django", "TensorFlow", "Pygame", "NumPy"])),
            # T8-03 同义改写
            dict(cid="T8-03", q="Python 现在最稳定的发行版本是多少？",
                 expected="原始答含3.12, Self-Check不应误拦",
                 judge=lambda a, files, chk: "3.12" in a),
            # T8-04 易混淆/假阳性（健身话题，应命中fitness，不混入其他文档关键信息）
            dict(cid="T8-04", q="健身每周建议几次、每次多久？",
                 expected="命中fitness, 原始答含每周3次与60分钟",
                 judge=lambda a, files, chk: ("3 次" in a or "三次" in a or "3次" in a)
                                             and "60" in a),
            # T8-05 知识库不存在
            dict(cid="T8-05", q="OceanBase 数据库的部署步骤是什么？",
                 expected="拒答【文档未找到相关内容】",
                 judge=lambda a, files, chk: "文档未找到相关内容" in a),
            # T8-06 文档内部冲突（synthetic 3.7 vs python 3.12）
            dict(cid="T8-06", q="文档中 Python 的当前稳定版本是两个不同的数字，分别是什么？",
                 expected="原始答识别冲突(3.7与3.12)，不武断单一结论",
                 judge=lambda a, files, chk: ("3.7" in a and "3.12" in a)),
            # T8-07 多文档混合：python + javascript（文件名校验用 .txt）
            dict(cid="T8-07", q="Python 和 JavaScript 分别是由谁、在哪年发布的？",
                 expected="同时召回python与javascript, 原始答合并两条不同文档来源信息",
                 judge=lambda a, files, chk: "Guido" in a and "Brendan" in a
                                             and "python_intro.txt" in files and "javascript_intro.txt" in files),
        ]

        for c in cases:
            docs, raw, final, chk = run(c["q"])
            files = files_of(docs)
            try:
                content_ok = c["judge"](raw, files, chk)
            except Exception:
                content_ok = False
            sc_ok = chk["verdict"] != "block"
            rep.add(f"{c['cid']} {c['q'][:18]}..",
                    c["expected"],
                    f"src={files}\n  原始答={raw[:150]!r}\n  final={final[:60]!r}, "
                    f"sc={chk['verdict']}({chk.get('grounded_facts')}/{chk.get('total_facts')}), "
                    f"内容正确={content_ok}, SC通过={sc_ok}",
                    content_ok and sc_ok)
            if content_ok and not sc_ok:
                rep.defect(f"{c['cid']}: 答案内容正确且源自文档，但被 Self-Check 误判 block 拦截 "
                           f"(grounded={chk.get('grounded_facts')}/{chk.get('total_facts')})。"
                           f"原始答案={raw[:100]!r}")

        rep.render()
        return 0 if rep.all_pass else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    import common  # noqa: F401
    raise SystemExit(main())