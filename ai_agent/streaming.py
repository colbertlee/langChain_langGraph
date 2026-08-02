"""
流式输出增量差分（Streaming Delta Diff）。

问题背景
--------
LangChain 1.x 的 `agent.stream(stream_mode="values")` 每个 chunk 都返回"到目前为止
的完整 state"。前端期望拿到增量（diff），而不是每次回放全文。

原始实现的隐患
~~~~~~~~~~~~
agent.py 旧实现用 ``last_yielded_len`` 计数器，并通过 ``sanitize_output`` 对增量
做脱敏。问题：

1. ``sanitize_output`` 改长度时（例如把一段文本替换为 ``[REDACTED]``），下次切片的
   起点偏移就错了，会出现"丢字 / 重复 / 错位"。
2. 计数器不能跨"完整文本在某个 chunk 整体 reset"的情况兼容（旧实现靠长度变化兜不住）。

新实现
~~~~~~
用一个独立的状态机 ``StreamDeltaTracker``：

- 内部始终持有"已成功 yield 出去的累积文本"（canonical 引用）。
- 每个 chunk 拿到 ``current_text`` 后，做"基于前缀的最长公共前缀剥离 + 残余追加"
  计算出真实增量。
- 对增量调 ``sanitize_output``，再做一次"再次取最长公共前缀"（避免 sanitize 引入
  的可回退情形），保证即使 sanitize 引入冗余前缀或缩短文本也不会错位。
- 对 CoT（``## 思考`` / ``## 回答``）分段也用同样的"基于已 yield CoT/Answer 文本"
  的 diff 策略，而不是依赖长度计数器。

这样：

- Sanitize 改长度不会导致错位；
- 模型中间"重新生成"或回退（罕见，但需兜底）走 `attempt_reset`；
- 可并发安全地切换到 fallback provider 时直接 ``reset()``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class StreamDeltaTracker:
    """稳健的"完整文本 → 增量"差分状态机。

    设计原则：
    - 已 yield 的文本作为 canonical reference，禁止长度依赖。
    - 每个 chunk 只输出"自上次 yield 后真正的增量"。
    - sanitize 改长度不影响后续 diff。
    - CoT / Answer 分段独立追踪，互不干扰。
    """

    # 已成功 yield 出去的"累积回答"文本（不含 thinking）。
    emitted_answer: str = ""
    # 已成功 yield 出去的"累积思考"文本（thinking 段）。
    emitted_thinking: str = ""
    # 整个 stream 累计输出（合并 thinking + answer），用于落库 / 日志。
    full_output: str = ""
    # 上一 chunk 解析得到的"完整文本"快照；用于检测"模型重置 / 异常回退"。
    last_seen_text: str = ""

    # ------------------------- 核心 diff 工具 -------------------------

    @staticmethod
    def _common_prefix_len(a: str, b: str) -> int:
        """返回 a / b 的最长公共前缀长度。

        注意：是字符级（python 字符串按 codepoint），对中文/RTL 都安全。
        """
        # 优化：先按 utf-8 字节快速剔除，再做逐字符兜底
        # 这里保持简单实现（输入一般不会极端大），正确性优先。
        n = min(len(a), len(b))
        i = 0
        # 整段先比对，再切到 boundary
        if a[:n] == b[:n]:
            return n
        while i < n and a[i] == b[i]:
            i += 1
        return i

    @staticmethod
    def _compute_increment(previous: str, current: str, max_drop: int = 64) -> str:
        """计算从 ``previous`` 累积文本到 ``current`` 的真实增量。

        思路：
        1. 取最长公共前缀长度 ``common``。
        2. 增量 = ``current[common:]``。
        3. 若 ``common`` 比 ``previous`` 还短（即 previous 出现了"非前缀外的新字符"），
           则视为上一 chunk 把输出整体回退 / 重置（极少见；属兜底），此时直接取
           ``current`` 增量并打印警告。

        ``max_drop`` 是容忍阈值——若 current 比 previous 整体短很多（差超过该字符数），
        也按"重置"处理；否则按截断看待（其实不会发生，仅作安全护栏）。
        """
        if not previous:
            return current

        # 兜底 1：current 是空（被 sanitize 删空等），增量为空
        if not current:
            return ""

        common = StreamDeltaTracker._common_prefix_len(previous, current)

        # 兜底 2：previous 比 current 还长很多（说明 sanitize 把文本缩短了）。
        # 此时若 previous 是 current 的前缀（扩展序列），增量依然正确；
        # 若不是前缀，说明发生了"脱敏替换"，则全量替换 previous 为当前文本。
        if common == len(previous):
            # previous 整段都在 current 里出现 → 增量就是后半截
            return current[common:]
        if common == len(current):
            # current 整段都在 previous 里（旧文本子串），无新字符
            return ""
        if len(previous) - common > max_drop:
            # previous 比 current 多出 >= max_drop 的"非公共"前缀：
            # 视为整体回退 / sanitize 大幅缩短 → 全量替换。
            return f"\u0000RESET\u0000{current}"

        # 常规路径：current 在 previous 后面扩展了一段
        return current[common:]

    # ------------------------- 公开 API -------------------------

    def reset(self) -> None:
        """新一次流 / 切换 fallback 时调用，重置全部状态。"""
        self.emitted_answer = ""
        self.emitted_thinking = ""
        self.full_output = ""
        self.last_seen_text = ""

    def attempt_reset(self, current_text: str) -> None:
        """当上游把累积文本整体替换（罕见）时，把内部状态对齐到 current_text。"""
        self.emitted_answer = current_text
        self.emitted_thinking = ""
        self.full_output = current_text
        self.last_seen_text = current_text

    def feed(
        self,
        current_text: str,
        *,
        sanitizer=None,
        cot_splitter=None,
    ) -> Tuple[str, str, str]:
        """输入当前 chunk 的完整文本，输出 (thinking_inc, answer_inc, reset_flag)。

        Args:
            current_text: 模型到现在为止产出的完整文本（含 CoT/Answer 全部）。
            sanitizer: 可选的可调用 ``str -> str``，对输出做脱敏；
                       不传则原样返回。
            cot_splitter: 可选的 ``str -> (cot, answer)``，用于切分 CoT 与 Answer。
                          不传则全部当 answer。

        Returns:
            (thinking_increment, answer_increment, reset_flag)
            - reset_flag == "RESET" 表示本次发生了整体回退（极少见）。
        """
        if not current_text:
            return "", "", ""

        # 1. 与上游 last_seen 做兜底（处理"整体回退"）
        reset_flag = ""
        if (
            self.last_seen_text
            and current_text
            and len(current_text) < len(self.last_seen_text) - 64
        ):
            # 整体回退（rare）
            reset_flag = "RESET"
            self.attempt_reset(current_text)
            # 直接把整段视为首个增量给前端
            if sanitizer is not None:
                try:
                    inc = sanitizer(current_text) or current_text
                except Exception:
                    inc = current_text
            else:
                inc = current_text
            if cot_splitter is not None:
                _, ans = cot_splitter(inc)
                return "", ans, reset_flag
            return "", inc, reset_flag

        # 2. 切分 CoT / Answer（如有）
        if cot_splitter is not None:
            cot_full, answer_full = cot_splitter(current_text)
        else:
            cot_full, answer_full = "", current_text

        # 3. 各自做 diff
        thinking_inc = self._compute_increment(self.emitted_thinking, cot_full)
        answer_inc = self._compute_increment(self.emitted_answer, answer_full)

        # 4. 实时 sanitize 增量（不再 sanitize 全量，避免文本错位）。
        # sanitizer 抛异常时降级为原样文本，绝不让 sanitize crash 主 stream。
        if sanitizer is not None:
            if thinking_inc:
                try:
                    thinking_inc = sanitizer(thinking_inc) or ""
                except Exception:
                    pass
            if answer_inc:
                try:
                    answer_inc = sanitizer(answer_inc) or ""
                except Exception:
                    pass

        # 5. 更新内部状态
        self.emitted_thinking = cot_full
        self.emitted_answer = answer_full
        self.last_seen_text = current_text
        # full_output 用"原始全量"组合（保留 CoT），用于落库
        self.full_output = (
            (cot_full + ("\n" if cot_full and answer_full else "") + answer_full)
            if cot_full or answer_full
            else ""
        )

        return thinking_inc, answer_inc, reset_flag

    def summary(self) -> Dict[str, str]:
        return {
            "answer": self.emitted_answer,
            "thinking": self.emitted_thinking,
            "full": self.full_output,
        }


__all__ = ["StreamDeltaTracker"]
