# -*- coding: utf-8 -*-
"""模块1：文档解析模块 —— 验证 txt 读取、编码、原文抽取。"""
import re
from common import ModuleReport, KB_FILES, read_raw_text, kb_path
import common


def paragraphs(text):
    return [p for p in re.split(r"\n+", text) if p.strip()]


def main():
    from file_parser import parse_file  # 被测：file_parser.parse_file

    rep = ModuleReport("模块1 文档解析")

    for fname in KB_FILES:
        raw_text = read_raw_text(fname)
        raw_bytes_len = len(open(kb_path(fname), "rb").read())

        parsed = parse_file(kb_path(fname), filename=fname)
        text = parsed.text if parsed is not None else None
        kind = parsed.kind if parsed is not None else None

        # T1.1 读取成功且类型为 text
        ok1 = parsed is not None and kind == "text" and bool(text)
        rep.add(
            f"[{fname}] 读取成功且 kind=txt", "kind=='text' 且非空",
            f"kind={kind}, len={len(text) if text else None}", ok1
        )

        # T1.2 原文保真：与源 UTF-8 文本逐字符一致
        ok2 = text == raw_text
        rep.add(
            f"[{fname}] 原文保真(逐字符一致)", "抽取文本 == 源文件内容",
            f"equal={ok2}, 抽取len={len(text) if text else None}, 源len={len(raw_text)}",
            ok2
        )

        # T1.3 无乱码 / 无 BOM / 无截断
        has_mojibake = (text or "").count("\ufffd") > 0
        bom_header = text is not None and text[:1] and text[0] == "\ufeff"
        ok3 = (not has_mojibake) and (not bom_header)
        rep.add(
            f"[{fname}] 无乱码/无BOM残留", "无\\ufffd、无\\ufeff",
            f"mojibake_cn={text.count(chr(0xFFFD)) if text else 0}, bom={bom_header}"
            if text else "text=None", ok3
        )

        # T1.4 无缺失段落：段落数一致
        src_paras = paragraphs(raw_text)
        out_paras = paragraphs(text) if text else []
        ok4 = len(src_paras) == len(out_paras)
        rep.add(
            f"[{fname}] 段落完整性", "段落数一致且内容一致",
            f"源段落={len(src_paras)}, 抽取段落={len(out_paras)}, "
            f"内容相同={out_paras == src_paras}", ok4
        )

        if not (ok1 and ok2 and ok3 and ok4):
            rep.defect(f"{fname}: 解析结果与源文件不一致。解码器元数据={parsed.meta if parsed else None}")

    passed = rep.render()
    print(f"模块1 通过 {rep.passed_total}/{rep.total}  -> all_pass={rep.all_pass}")
    return 0 if rep.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())