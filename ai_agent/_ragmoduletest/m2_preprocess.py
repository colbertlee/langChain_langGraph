# -*- coding: utf-8 -*-
"""模块2：文本预处理 —— 清洗但保留段落语义边界。"""
import re
from common import ModuleReport, KB_FILES, read_raw_text


def paragraphs(text):
    return [p for p in re.split(r"\n+", text) if p.strip()]


def main():
    from rag import clean_text  # 被测：rag.clean_text

    rep = ModuleReport("模块2 文本预处理")

    # ---------- 子组A：对真实源文本清洗，不得篡改语义 ----------
    for fname in KB_FILES:
        src = read_raw_text(fname)
        out = clean_text(src)
        src_paras = paragraphs(src)
        out_paras = paragraphs(out)
        # A1 语义完整：去空行后段落文本内容完全一致（clean 只动空白，不动字词）
        ok_content = out_paras == src_paras
        # A2 段落边界保留：仍存在双换行分隔符（未被压成单行）
        ok_boundary = "\n\n" in out or len(out_paras) <= 1
        rep.add(
            f"[{fname}] 清洗不篡改原文（段落内容逐一相等）",
            "每段内容一致", f"段落数 out={len(out_paras)} vs src={len(src_paras)}, "
            f"内容一致={ok_content}", ok_content
        )
        rep.add(
            f"[{fname}] 段落边界保留(不清空不单行化)",
            "保\\n\\n分隔或单段", f"含\\n\\n={ok_boundary}", ok_boundary
        )
        if not (ok_content and ok_boundary):
            rep.defect(f"{fname} clean_text 语义被篡改或段落被破坏")

    # ---------- 子组B：注入脏字符验证清洗规则 ----------
    body = "这是第一段内容。\n这是第二段内容。"
    # B1 连续空行压缩：5 个换行应压成 \n\n
    t1 = "第一段。\n\n\n\n\n第二段。"
    r1 = clean_text(t1)
    ok_b1 = "\n\n" in r1 and not re.search(r"\n{3,}", r1)
    rep.add("连续空行压缩(>=3 -> \\n\\n)", "无 3+ 连续换行",
            f"in={t1!r} out={r1!r}", ok_b1)
    if not ok_b1:
        rep.defect("B1 连续 3+ 换行未压缩到 \\n\\n")

    # B2 边界保护：恰好 2 个换行 (\n\n) 不应被压缩、不应被单行化
    t2 = "甲段。\n\n乙段。"
    r2 = clean_text(t2)
    ok_b2 = "\n\n" in r2
    rep.add("边界保护(保留 \\n\\n，不单行化)", "输出含双换行",
            f"in={t2!r} out={r2!r}", ok_b2)
    if not ok_b2:
        rep.defect("B2 双换行段落分隔被破坏/被单行化")

    # B3 CRLF 与孤立 CR 归一化为 \\n
    t3 = "行一\r\n行二\r行三"
    r3 = clean_text(t3)
    ok_b3 = ("\r" not in r3) and r3.count("\n") == 2
    rep.add("CRLF/孤立CR归一化为\\n", "无\\r 且换行数正确",
            f"in={t3!r} out={r3!r}", ok_b3)
    if not ok_b3:
        rep.defect("B3 \\r 未正确归一化")

    # B4 不可见控制字符 / 零宽 / 全角空格 / 制表符清理
    t4 = "含\x00NUL\u200b零宽\u200c\u200d\t制表符＋全角"
    r4 = clean_text(t4)
    bad = [c for c in ("\x00", "\u200b", "\u200c", "\u200d") if c in r4]
    ok_b4 = (not bad) and "\t" not in r4
    rep.add("去NUL/零宽/制表符/全角空格", "不含这些脏字符",
            f"out={r4!r} 残留脏字符={bad}", ok_b4)
    if not ok_b4:
        rep.defect("B4 不可见/控制字符未清除")

    # B5 语义保真：clean 后句子仍完整可读（不出现断句）
    sample = read_raw_text("python_intro.txt")
    r5 = clean_text(sample)
    sentences_out = [s for s in re.split(r"[。！？\n]", r5) if s.strip()]
    key_sents = ["Python 是一种高级、通用、解释型编程语言",
                 "它由 Guido van Rossum 于 1991 年发布",
                 "当前稳定版本是 Python 3.12"]
    missing = [k for k in key_sents if k not in r5]
    ok_b5 = not missing
    rep.add("语义保真（关键句完整保留）", "关键句子均在输出中出现",
            f"缺失关键句={missing}", ok_b5)
    if not ok_b5:
        rep.defect("B5 清洗破坏了句子完整性")

    passed = rep.render()
    print(f"模块2 通过 {rep.passed_total}/{rep.total} -> all_pass={rep.all_pass}")
    return 0 if rep.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())