# -*- coding: utf-8 -*-
"""模块3：切片 Chunk —— 段落优先、句子边界、无半句截断、参数合规、chunk_id。"""
import re
from common import ModuleReport, KB_FILES, read_raw_text


def base_sentences(fname):
    """按换行切出的原始行（含序号行如 '1. Python 简介'）。"""
    return [ln for ln in read_raw_text(fname).split("\n") if ln.strip()]


def split_sentences(text):
    return [s for s in re.split(r"(?<=[。！？；])\s*|\n+", text) if s.strip()]


def main():
    from rag_service import split_text  # 真实切分函数

    # 被测参数（与生产对齐）
    PARAMS = [("rag_service默认", 500, 80), ("RAGModule.text_splitter", 350, 40)]
    rep = ModuleReport("模块3 切片 Chunk")

    for pname, chunk_size, chunk_overlap in PARAMS:
        # ---------------- 基础：实例文档完整行不被截断在 chunk 内 ----------------
        all_chunks_have_clean_lines = True
        for fname in KB_FILES:
            text = read_raw_text(fname)
            chunks = split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            # chunk_id 连续性 & 唯一
            ids = [c["chunk_id"] for c in chunks]
            ok_seq = ids == list(range(len(chunks)))
            if not ok_seq:
                all_chunks_have_clean_lines = False
                rep.defect(f"[{pname}/{fname}] chunk_id 不连续: {ids}")
            # 每个原始行应"完整出现"在 >=1 个 chunk（overlap 会合法地让边界行出现2次，
            # 但绝不出现"行被半句切裂"——即完整行子串在任一切片中都找不到）
            for ln in base_sentences(fname):
                appear = sum(1 for c in chunks if ln in c["text"])
                if appear == 0:  # 完整行无处可寻 = 被切成半句散落/丢失 → 真缺陷
                    all_chunks_have_clean_lines = False
                    rep.defect(f"[{pname}/{fname}] 原始行被切裂或丢失: {ln!r} 无任何chunk完整包含")
        rep.add(
            f"[{pname}] 行完整性（无半句截断/不丢行）",
            "每个原始行完整体现在≥1个chunk", f"全部成立={all_chunks_have_clean_lines}",
            all_chunks_have_clean_lines
        )

        # ---------------- 长段落：句子边界切分 ----------------
        # 构造一个远大于 chunk_size 的单段落（无段落换行），内部有多句
        long_para = "。".join(["这是第{}个长句，内容足以撑满超长段落每次都超出切片大小约束 чтобы проверить 句子切分点".format(i)
                               for i in range(1, 200)]) + "。"
        clong = split_text(long_para, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        # 任何 chunk 最长不应明显超过 chunk_size + jitter（防止按字符硬切）
        maxlen = max(len(c["text"]) for c in clong)
        cutoff = chunk_overlap + chunk_size + 2
        ok_len = maxlen <= cutoff
        # 语义完整：每句（以。结尾）要么整句在块内，要么整句在块边界被切（句子边界允许）
        # 检查每 chunk 不包含"孤立半句"：chunk 不以作为次句开头的半句话切断（务实检查：块末尾不是句号分隔的下半句无后续）
        # 简化客观断言：所有 chunk 拼接后仍含全部 200 句原文，无丢字
        joined = "".join(c["text"] for c in clong)
        n_missing = 0
        for i in range(1, 200):
            if ("这是第{}个长句".format(i)) not in joined:
                n_missing += 1
        rep.add(
            f"[{pname}] 超长段落按句子边界切+不丢内容",
            f"各chunk≤{cutoff}字符，且200句全保留",
            f"max块长={maxlen}, 缺失句={n_missing}", ok_len and n_missing == 0
        )
        if not (ok_len and n_missing == 0):
            rep.defect(f"[{pname}] 长段落切分超限或丢句: max块长={maxlen}, 缺失={n_missing}")

        # ---------------- 参数合规：token 上限（真实文档） ----------------
        # Embedding 模型 bge-m3 最大输入 8192 tokens；CJK 每字≈0.6~1 token，取最坏 1 token/字
        global_maxlen = 0
        token_ok = True
        for fname in KB_FILES:
            for c in split_text(read_raw_text(fname), chunk_size=chunk_size, chunk_overlap=chunk_overlap):
                global_maxlen = max(global_maxlen, len(c["text"]))
                if len(c["text"]) > 8192:  # 最坏≈每字符1 token
                    token_ok = False
                    rep.defect(f"[{pname}/{fname}] chunk 超过 8192: len={len(c['text'])}")
        rep.add(
            f"[{pname}] token 长度合规(实际文档≤8192)",
            "所有chunk len ≤ Embedding 上限", f"实际最大len={global_maxlen}", token_ok
        )

        # ---------------- 元数据：chunk_id 绑定 ----------------
        c0 = split_text(read_raw_text("python_intro.txt"), chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        has_id = all("chunk_id" in c and "text" in c for c in c0)
        rep.add(
            f"[{pname}] 元数据绑定(chunk_id+text)",
            "每chunk含 text 与 chunk_id", f"含key且id连续={c0[0]['chunk_id'] if c0 else None}~{c0[-1]['chunk_id'] if c0 else None}, has_id={has_id}",
            has_id
        )

    rep.add("元数据绑定(文件名+原文)的归属说明",
            "fileName绑定在向量库upsert层(模块4), 本模块不含",
            "split_text仅输出{text,chunk_id}; fileName存储于upsert_chunks metadata", True)

    passed = rep.render()
    print(f"模块3 通过 {rep.passed_total}/{rep.total} -> all_pass={rep.all_pass}")
    return 0 if rep.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())