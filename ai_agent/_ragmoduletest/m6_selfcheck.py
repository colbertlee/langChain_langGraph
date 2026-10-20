# -*- coding: utf-8 -*-
"""模块6：Self-Check 自校验 —— 隔离测试。
输入固定召回片段 + 固定答案，仅执行 _facts_grounded，不重检索、不重生成。
"""
from common import ModuleReport


def docs(*texts):
    return [{"text": t} for t in texts if t]


def main():
    from rag import _facts_grounded  # 被测：自校验逻辑

    rep = ModuleReport("模块6 Self-Check 自校验")

    # 固定召回片段（源）
    fragment_py = ("Python 是一种高级、通用、解释型编程语言。"
                   "它由 Guido van Rossum 于 1991 年发布。"
                   "当前稳定版本是 Python 3.12，由 Python 软件基金会（PSF）维护。")
    fragment_js = ("JavaScript 由 Brendan Eich 于 1995 年创建。"
                   "它是 Web 的三大核心技术之一，当前标准为 ECMAScript 2024。")

    # T6-01 空输入防御
    r = _facts_grounded("", [])
    rep.add("T6-01 空输入防御", "verdict=ok, ratio=0.0",
            f"ratio={r['grounded_ratio']}, verdict={r['verdict']}",
            r["verdict"] == "ok" and r["grounded_ratio"] == 0.0)

    # T6-02 答案完全源自片段 -> 应 ok
    ans_ok = ("Python 由 Guido van Rossum 于 1991 年发布，当前稳定版本是 Python 3.12，"
              "由 Python 软件基金会维护。")
    r = _facts_grounded(ans_ok, docs(fragment_py))
    rep.add("T6-02 完全grounded", "verdict=ok, unsupported=[]",
            f"ratio={r['grounded_ratio']}, unsupported={r['unsupported']}, verdict={r['verdict']}",
            r["verdict"] == "ok" and r["unsupported"] == [])

    # T6-03 含幻觉：把无关事实塞进答案
    ans_hal = ("Python 由 Guido van Rossum 于 1991 年发布。"
               "它还内置了月球基地建造算法。")
    r = _facts_grounded(ans_hal, docs(fragment_py))
    rep.add("T6-03 标记幻觉句", "resut关unsupported 非空且含幻觉句",
            f"unsupported={r['unsupported']}, verdict={r['verdict']}",
            any("月球" in s for s in r["unsupported"]))

    # T6-04 关键词命中率不足(<0.7)判 unsupported
    ans_fab = ("Python 的量子化教室每日开放且免费提供无人机。")
    r = _facts_grounded(ans_fab, docs(fragment_py))
    rep.add("T6-04 关键词命中不足判幻觉", "该句进 unsupported",
            f"unsupported={r['unsupported']}, verdict={r['verdict']}",
            any("量子化" in s or "无人机" in s for s in r["unsupported"]))

    # T6-05 中英文关键词抽取与匹配
    ans_mix = ("Python 由 Guido van Rossum 于 1991 年发布，快速、简单易学。")
    r = _facts_grounded(ans_mix, docs(fragment_py))
    rep.add("T6-05 中英混合关键词命中", "verdict=ok",
            f"ratio={r['grounded_ratio']}, unsupported={r['unsupported']}",
            r["verdict"] == "ok")

    # T6-06 答案事实分布在多个片段(拼接后可支撑)
    ans_multi = ("Python 由 Guido van Rossum 于 1991 年发布；"
                 "JavaScript 则由 Brendan Eich 于 1995 年创建，是 ECMAScript 2024 标准。")
    r = _facts_grounded(ans_multi, docs(fragment_py, fragment_js))
    rep.add("T6-06 多片段拼合都能支撑", "verdict=ok, unsupported=[]",
            f"ratio={r['grounded_ratio']}, unsupported={r['unsupported']}",
            r["verdict"] == "ok" and r["unsupported"] == [])

    # T6-07 verdict 分级：ok / warn / block
    v_ok = _facts_grounded(ans_ok, docs(fragment_py))["verdict"]
    ans_semisupported = ("Python 由 Guido van Rossum 于 1991 年发布。"
                         "Python 每月产出蓝色能量水晶。Python 还会说四种方言。")
    v_warn_or_block = _facts_grounded(ans_semisupported, docs(fragment_py))["verdict"]
    rep.add("T6-07 verdict 分级(ok/非ok)",
            "ok=0.8+, 半幻觉应非ok", f"全支撑verdict={v_ok}, 半幻觉verdict={v_warn_or_block}",
            v_ok == "ok" and v_warn_or_block in ("warn", "block"))

    passed = rep.render()
    print(f"模块6 通过 {rep.passed_total}/{rep.total} -> all_pass={rep.all_pass}")
    return 0 if rep.all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())