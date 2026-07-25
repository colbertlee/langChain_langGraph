"""
LLM 语义纠错 + 领域上下文注入

把 ASR 文本送进 LLM，让它基于 domain_context 改写：
- 同音字纠正（"支护宝" → "支付宝"）
- 领域术语规范化（"Langhain" → "LangChain"）
- 断句 / 标点补全
- 上下文注入（在送 LLM 时附带"这是 XX 领域的语音输入"）

依赖：
- 可注入任意 LLM callable(text, prompt) -> str
- 缺 LLM 时降级：无差别返回原文本
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


DEFAULT_CORRECT_PROMPT = """你是语音转文字（ASR）后处理助手。请把下面的 ASR 原始文本改写成正确的自然语言句子。

领域背景：{domain}

要求：
1. 修正同音字、近音字、ASR 常见错误。
2. 将口语化表达转化为书面语句子。
3. 仅在必要时补全标点符号。
4. 不要添加原文中没有的信息。
5. 输出纯文本（不包含任何解释、注释或前后缀）。

示例：
输入：嗯那个我今天要个支护宝付款
输出：我今天要用支付宝付款。

输入：打开 long chain 文档
输出：打开 LangChain 文档。

ASR 原始文本：
{text}
"""

DEFAULT_CONTEXT_INJECTION = """【语音输入上下文】
- 领域：{domain}
- ASR 引擎：{provider}
- ASR 置信度：{confidence:.2f}
- 命中热词：{hotwords}
- 用户已确认：{user_confirmed}

提示：以上文本是用户语音输入的转写结果，请按上述领域语义理解。"""


class LLMSemanticCorrector:
    """
    使用 LLM 做语义级纠错 + 上下文注入。

    使用：
        corrector = LLMSemanticCorrector(llm_callable=my_llm, domain="AI Agent 开发")
        corrected = corrector.correct("打开 long chain 文档")
    """

    def __init__(
        self,
        llm_callable: Optional[Callable[[str], str]] = None,
        domain: Optional[str] = None,
        prompt_template: Optional[str] = None,
    ):
        self.llm = llm_callable
        self.domain = domain or os.getenv("AUDIO_DOMAIN_CONTEXT", "")
        self.prompt_template = prompt_template or DEFAULT_CORRECT_PROMPT

    def correct(self, text: str, domain: Optional[str] = None) -> str:
        if not text or not text.strip():
            return text
        if self.llm is None:
            return text
        dom = domain or self.domain or "通用"
        prompt = self.prompt_template.format(domain=dom, text=text)
        try:
            out = self.llm(prompt)
            return (out or text).strip()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[LLMSemanticCorrector] failed: {e}")
            return text

    def inject_context(
        self,
        text: str,
        asr_meta: Dict[str, Any],
        domain: Optional[str] = None,
    ) -> str:
        """在送 LLM 时，把 ASR 上下文作为 hint 拼到文本前"""
        if not text:
            return text
        dom = domain or self.domain or "通用"
        hotwords = asr_meta.get("hotwords_hit") or []
        hotwords_str = ", ".join(hotwords) if hotwords else "无"
        hint = DEFAULT_CONTEXT_INJECTION.format(
            domain=dom,
            provider=asr_meta.get("provider", "unknown"),
            confidence=float(asr_meta.get("confidence", 0.0) or 0.0),
            hotwords=hotwords_str,
            user_confirmed=bool(asr_meta.get("user_confirmed", False)),
        )
        return f"{hint}\n\n用户语音文本：\n{text}"


# ============================================================
# 默认 LLM 适配：从现有 agent 拉一个 ChatModel
# ============================================================

def make_default_llm_corrector():
    """
    构造一个依赖 langchain ChatModel 的 corrector。
    仅在有 LLM 凭据时启用，否则返回 None。
    """
    try:
        # 延迟导入，避免循环依赖
        from config import MODEL_PROVIDER, MODEL_NAME, OPENAI_API_KEY
        from langchain_openai import ChatOpenAI

        if not OPENAI_API_KEY:
            return None

        llm = ChatOpenAI(model=MODEL_NAME, temperature=0.0)
        domain = os.getenv("AUDIO_DOMAIN_CONTEXT", "")

        def _call(prompt: str) -> str:
            from langchain_core.messages import HumanMessage
            r = llm.invoke([HumanMessage(content=prompt)])
            return getattr(r, "content", "") or ""

        return LLMSemanticCorrector(llm_callable=_call, domain=domain)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[make_default_llm_corrector] init failed: {e}")
        return None
