# -*- coding: utf-8 -*-
"""模块7：Self-Check 自校验 —— 隔离测试。
前置：模块6全部通过；输入【固定召回片段 + 固定答案】，
仅执行 _facts_grounded，不重新检索、不重生成答案。
被测：rag._facts_grounded。
"""
from common import ModuleReport


def docs(*texts):
    return [{"text": t} for t in texts if t]


def main():
    from rag import _facts_grounded

    rep = ModuleReport("模块7 Self-Check 自校验")

    fragment_py = ("Python 是一种高级、通用、解释型编程语言。"
                   "它由 Guido van Rossum 于 1991 年发布。"
                   "当前稳定版本是 Python 3.12，由 Python 软件基金会（PSF）维护。")
    fragment_js = ("JavaScript 由 Brendan Eich 于 1995 年创建。"
                   "它是 Web 的三大核心技术之一，当前标准为 ECMAScript 2024。")

    # T7-01 答案完全来自片段 -> 校验通过
    ans_ok = ("Python 由 Guido van Rossum 于 1991 年发布，当前稳定版本是 Python 3.12，"
              "由 Python 软件基金会维护。")
    r = _facts_grounded(ans_ok, docs(fragment_py))
    rep.add("T7-01 完全grounded → 通过",
            "verdict=ok, unsupported=[]", f"ratio={r['grounded_ratio']}, "
            f"unsupported={r['unsupported']}, verdict={r['verdict']}",
            r["verdict"] == "ok" and r["unsupported"] == [])

    # T7-02 含编造内容 → 标记幻觉
    ans_hal = ("Python 由 Guido van Rossum 于 1991 年发布。它内置了月球基地建造算法。")
    r = _facts_grounded(ans_hal, docs(fragment_py))
    rep.add("T7-02 编造内容被识别",
            "unsupported 含幻觉句，verdict=block", f"unsupported={r['unsupported']}, "
            f"verdict={r['verdict']}", "月球" in str(r["unsupported"]))

    # T7-03 引用编号错误：答案引用与召回不符（此处校验的是事实本体）
    ans_badref = ("Python 由 Brendan Eich 于 1995 年创建并被 Python 基金会维护。")
    r = _facts_grounded(ans_badref, docs(fragment_py))
    rep.add("T7-03 引用事实错误被识别",
            "Eich/1995 非Python事实→unsupported", f"unsupported={r['unsupported']}, "
            f"verdict={r['verdict']}", any("Eich" in s for s in r["unsupported"]))

    # T7-04 冲突合并：强行合并冲突 → 标记不可靠 / 至少指出
    c1 = {"text": "某产品价格 99 元。"}
    c2 = {"text": "某产品价格 199 元。"}
    ans_conflict = "某产品的价格是 99 元，同时也是 199 元。"
    r = _facts_grounded(ans_conflict, docs("某产品价格 99 元。", "某产品价格 199 元。"))
    conflict_detected = any("99" in s and "199" in s for s in r["unsupported"]) or \
                        r["verdict"] in ("warn", "block")
    rep.add("T7-04 冲突场景标记",
            "识别自相矛盾(99且199)，标记不可靠",
            f"unsupported={r['unsupported']}, verdict={r['verdict']}", conflict_detected)

    # T7-05 文档无信息但模型编造 → 判定无效
    ans_fab = "Python 由 SpaceX 发射到月球基地。"
    r = _facts_grounded(ans_fab, docs(fragment_py))
    rep.add("T7-05 无支撑编造判定无效",
            "unsupported 含幻觉句，verdict=block",
            f"unsupported={r['unsupported']}, verdict={r['verdict']}",
            any("SpaceX" in s for s in r["unsupported"]) and r["verdict"] == "block")

    # T7-06 混合真假：精准定位单条幻觉，区分有效/幻觉
    ans_mix = ("Python 由 Guido van Rossum 于 1991 年发布。"
               "Python 每天会产出蓝色能量水晶。")
    r = _facts_grounded(ans_mix, docs(fragment_py))
    rep.add("T7-06 真假混合精准定位",
            "有效句grounded，幻觉句进unsupported",
            f"grounded={r['grounded_facts']}/{r['total_facts']}, "
            f"unsupported={r['unsupported']}",
            any("能量水晶" in s for s in r["unsupported"]) and r["grounded_facts"] >= 1)

    # T7-07 空答案 /【文档未找到】场景 → 合规无报错
    r1 = _facts_grounded("", docs(fragment_py))
    r2 = _facts_grounded("文档未找到相关内容", docs(fragment_py))
    ok = (r1["verdict"] == "ok") and (r2["verdict"] == "ok")
    rep.add("T7-07 空/拒答场景合规",
            "verdict=ok 无报错", f"空:{r1['verdict']}, 拒答:{r2['verdict']}", ok)

    passed = rep.render()
    print(f"模块7 通过 {rep.passed_total}/{rep.total} -> all_pass={rep.all_pass}")
    return 0 if rep.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())