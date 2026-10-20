# -*- coding: utf-8 -*-
"""模块4：向量化 & 向量入库 —— Embedding 调用、id 映射、相似度自检。

后端：本机 Ollama 的 bge-m3（用户指定 Ollama 作为 Embedding 后端）。
"""
import math
import os
import shutil
import tempfile

import numpy as np
from common import ModuleReport, KB_FILES, read_raw_text, AGENT_DIR


def cosine(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na = np.linalg.norm(a) or 1.0
    nb = np.linalg.norm(b) or 1.0
    return float(np.dot(a, b) / (na * nb))


def main():
    from vector_store import VectorStore, OllamaEmbedding

    E = OllamaEmbedding(model="bge-m3", base_url="http://localhost:11434", timeout=300)
    tmp = tempfile.mkdtemp(prefix="ragmoduletest_chroma_")
    try:
        vs = VectorStore(persist_dir=tmp, collection_name="m4test", embedding=E)
        rep = ModuleReport("模块4 向量化 & 入库")

        # ---- T4.1 Embedding 调用成功、维度正确、非降级 ----
        sample = ["Python 由 Guido van Rossum 于 1991 年发布。", "健身新手指南。"]
        try:
            vecs = E.embed_documents(sample)
            dims = [len(v) for v in vecs]
            ok_dim = all(d == 1024 for d in dims)  # bge-m3 dim=1024
            rep.add("Embedding 调用成功(bge-m3)",
                    "返回非空 1024 维向量", f"维度={sorted(set(dims))}", bool(vecs) and ok_dim)
        except Exception as e:
            ok_dim = False
            rep.add("Embedding 调用成功(bge-m3)", "bge-m3 应返回1024维", f"异常: {e}", False)
            rep.defect("T4.1 Ollama bge-m3 embedding 调用失败")

        # ---- T4.2/4.3 入库 + id 映射 + 原文非截断 ----
        chunks = []
        for fname in KB_FILES[:3]:  # python/javascript/java 三文件切片入库
            from rag_service import split_text
            for c in split_text(read_raw_text(fname), chunk_size=500, chunk_overlap=80):
                c["page"] = None
                chunks.append({"text": c["text"], "chunk_id": c["chunk_id"],
                               "__file": fname})
        text_by_cid = {(os.path.splitext(ch["__file"])[0], ch["chunk_id"]): ch["text"]
                       for ch in chunks}

        sess = "mod4-session"
        file_ids = {}
        ok_ids = True
        for fname in KB_FILES[:3]:
            fid = os.path.splitext(fname)[0]
            file_ids[fname] = fid
            chs = [c for c in chunks if c["__file"] == fname]
            ids = vs.upsert_chunks(chunks=chs, session_id=sess, file_id=fid, file_name=fname)
            expected = [f"{sess}::{fid}::{c['chunk_id']}" for c in chs]
            if ids != expected:
                ok_ids = False
                rep.defect(f"{fname}: id 格式不符 {ids} != {expected}")
        rep.add("T4.2/4.3 id 映射格式正确(session::file::chunk)", "id 精确匹配",
                f"文件数=3", ok_ids)

        # 反向取回：collection.get(ids) 校验 原文未截断
        col = vs.collection
        all_ids = [f"{sess}::{fid}::{c['chunk_id']}" for fname in KB_FILES[:3]
                   for c in chunks if c["__file"] == fname
                   for fid in [file_ids[fname]]]
        got = col.get(ids=all_ids, include=["documents", "metadatas"])
        got_text = dict(zip(got["ids"], got["documents"]))
        ok_map = True
        for c in chunks:
            cid = f"{sess}::{file_ids[c['__file']]}::{c['chunk_id']}"
            if got_text.get(cid) != c["text"]:
                ok_map = False
                rep.defect(f"原文未完整取回: {cid}")
                break
        rep.add("向量库→原文 一一对应(经get反查非截断)", "取回文本==入块原文",
                f"chunk总数={len(chunks)}", ok_map)

        # ---- T4.4 相似度自检 ----
        # 同文本向量余弦 ≈ 1
        t = "Python 是一种高级、通用、解释型编程语言。"
        v1 = E.embed_documents([t])[0]
        v2 = E.embed_documents([t])[0]
        c_same = cosine(v1, v2)
        # 无关文本
        unrelated = "青蛙在池塘边跳来跳去，吃着蚊虫。"
        vU = E.embed_documents([unrelated])[0]
        c_unrel = cosine(v1, vU)
        # 相关但不同措辞
        related = "Python 由 Guido van Rossum 于 1991 年发布。"
        vR = E.embed_documents([related])[0]
        c_rel = cosine(v1, vR)
        ok_similarity = c_same > 0.98 and c_unrel < c_rel
        rep.add("T4.4 相似度自检(同文本≈1 / 无关更远)",
                "同文本cos≈1, 无关cos<相关cos",
                f"same={c_same:.4f}, related={c_rel:.4f}, unrelated={c_unrel:.4f}",
                ok_similarity)
        if not ok_similarity:
            rep.defect("T4.4 余弦相似度区分度异常")

        # ---- T4.5 入库后 query 精确命中自身 ----
        q = chunks[0]["text"]
        top = vs.query(query_text=q, session_id=sess, top_k=5, min_score=0.0)
        hit = top[0] if top else None
        ok_hit = hit and hit["text"] == chunks[0]["text"] and abs(hit["score"] - 1.0) < 0.05
        rep.add("T4.5 查询自文本顶级命中自身", "top1 为自身且score≈1",
                f"top1.score={hit['score'] if hit else None}, 文本一致={hit and hit['text']==chunks[0]['text']}",
                ok_hit)
        if not ok_hit:
            rep.defect("T4.5 自查询未能命中已入库 chunk")

        passed = rep.render()
        print(f"模块4 通过 {rep.passed_total}/{rep.total} -> all_pass={rep.all_pass}")
        return 0 if rep.all_pass else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())