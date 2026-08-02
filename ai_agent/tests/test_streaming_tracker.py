"""StreamDeltaTracker 单元测试（Day 1-2 回归用）。

设计契约
--------
- ``feed(current)`` 输出 ``(thinking_inc, answer_inc, reset_flag)``。
- 对增量做 sanitize 只用于 *输出给前端*；内部 ``emitted_answer`` 仍然以
  ``current`` 原始值为 canonical reference —— 这是保证后续 diff 不受 sanitize
  长度变化影响的关键。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from streaming import StreamDeltaTracker


# ---- 基础追加 ----

def test_first_chunk_yields_full_text():
    t = StreamDeltaTracker()
    ti, ai, reset = t.feed("hello world")
    assert ti == "" and reset == ""
    assert ai == "hello world"


def test_append_chunk_yields_only_increment():
    t = StreamDeltaTracker()
    t.feed("hello ")
    ti, ai, _ = t.feed("hello world")
    assert ai == "world"


def test_no_change_yields_empty_increment():
    t = StreamDeltaTracker()
    t.feed("stable")
    ti, ai, _ = t.feed("stable")
    assert ai == "" and ti == ""


# ---- sanitize 改长度（关键回归：之前生产 bug）----

def test_sanitize_shortens_text_does_not_misalign():
    """sanitizer 把 "secret" 换成 "[REDACTED]"（不同长度），后续不应错位。"""

    def redactor(s: str) -> str:
        return s.replace("secret", "[REDACTED]")

    t = StreamDeltaTracker()
    # chunk1 含有 secret，被脱敏成更短的 [REDACTED]
    _, a1, _ = t.feed("The secret", sanitizer=redactor)
    # 输出应当是脱敏后的字符串
    assert a1 == "The [REDACTED]"
    # 关键：内部 emitted_answer 仍然是原值 "The secret"，下一个 chunk 做前缀 diff
    # 时才不会错位
    assert t.emitted_answer == "The secret"

    _, a2, _ = t.feed("The secret is hidden", sanitizer=redactor)
    # 脱敏后的增量：原增量 " is hidden" → 脱敏后 " is hidden"
    assert "hidden" in a2
    assert a2.startswith(" ")


def test_sanitize_adds_prefix_does_not_misalign():
    """sanitizer 在每段增量外加包装，diff 不应错位。"""

    def prefixer(s: str) -> str:
        return f"<<{s}>>"

    t = StreamDeltaTracker()
    _, a1, _ = t.feed("alpha", sanitizer=prefixer)
    assert a1 == "<<alpha>>"
    # 内部 emit 仍是原值（不被 sanitize 影响），这样后续 diff 才稳
    assert t.emitted_answer == "alpha"
    # 第二个 chunk 完整文本"alpha gamma"→原增量" gamma"→脱敏后"<< gamma>>"
    _, a2, _ = t.feed("alpha gamma", sanitizer=prefixer)
    # 关键：长出字符" gamma"被正确识别（而不是"alpha"整段再 yield 一次）
    assert a2 == "<< gamma>>"
    # 第二轮：再追加字符" delta"，原增量" delta" → "<< delta>>"
    _, a3, _ = t.feed("alpha gamma delta", sanitizer=prefixer)
    assert a3 == "<< delta>>"


def test_sanitizer_raises_falls_back():
    """sanitizer 抛出异常时，sanitize 仍要返回原文本（不可崩主流程）。"""

    def bad(s: str) -> str:
        raise RuntimeError("sanitizer crashed")

    t = StreamDeltaTracker()
    # 不应抛
    _, a1, _ = t.feed("hello", sanitizer=bad)
    assert a1 == "hello"


# ---- CoT 拆分段 ----

def cot_split(text: str):
    """简易 CoT 切分：'## 思考 ... ## 回答 ...' → (cot, answer)。"""
    if "## 思考" not in text:
        return "", text
    head, _, rest = text.partition("## 思考")
    cot_part, _, answer_part = rest.partition("## 回答")
    cot = (head + "## 思考" + cot_part).strip()
    answer = answer_part.strip()
    return cot, answer


def test_cot_split_produces_thinking_then_answer():
    t = StreamDeltaTracker()
    full = "## 思考\n我想\n## 回答\n你好"
    ti, ai, _ = t.feed(full, cot_splitter=cot_split)
    assert "我想" in ti
    assert "你好" in ai


def test_cot_split_incremental_only():
    t = StreamDeltaTracker()
    # 第一步只产出 CoT 段
    _, _, _ = t.feed("## 思考\n我想", cot_splitter=cot_split)
    # 第二步扩出 Answer 段
    ti, ai, _ = t.feed("## 思考\n我想\n## 回答\n你好", cot_splitter=cot_split)
    # thinking 段已存在 → 无新增量
    assert ti == ""
    # answer 增量只含新增内容
    assert ai == "你好"


# ---- 重置（fallback 切换或异常回退）----

def test_reset_clears_state():
    t = StreamDeltaTracker()
    t.feed("accumulated text")
    assert t.emitted_answer == "accumulated text"
    t.reset()
    assert t.emitted_answer == ""
    _, a1, _ = t.feed("fresh start")
    assert a1 == "fresh start"


def test_feed_detects_major_text_shrink_as_reset():
    """上游把累积文本大幅缩短（异常回退），tracker 触发 RESET。"""
    t = StreamDeltaTracker()
    # 70+ 字符，下一次只有 5 字符 → 差 65 > 阈值 64 → 触发 RESET
    t.feed("this is a fairly long accumulated text that spans well over sixty four chars")
    _, ai, flag = t.feed("short")
    assert flag == "RESET"
    # RESET 后第一个 chunk 内全文视为增量
    assert "short" in ai


# ---- 整体 ----

def test_summary_after_appends():
    t = StreamDeltaTracker()
    t.feed("a")
    t.feed("ab")
    t.feed("abc")
    s = t.summary()
    assert s["answer"] == "abc"


def test_full_output_contains_everything_after_chunks():
    t = StreamDeltaTracker()
    t.feed("a")
    t.feed("ab")
    t.feed("abc")
    assert t.full_output == "abc"


def test_mixed_cot_and_plain():
    """同一会话里从'有 CoT'切换到'无 CoT'（罕见），不应崩。"""
    t = StreamDeltaTracker()
    t.feed("## 思考\n想了\n## 回答\n答1", cot_splitter=cot_split)
    _, a2, _ = t.feed("## 回答\n答2", cot_splitter=cot_split)
    # 没有新 thinking 段；answer 段可能整体 reset
    assert isinstance(a2, str)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
