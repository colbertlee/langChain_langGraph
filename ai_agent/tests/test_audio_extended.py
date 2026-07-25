"""
audio_streaming / audio_semantic / audio_feedback 单元测试
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import struct
import tempfile
import wave
from pathlib import Path

import pytest


# ============================================================
# 工具
# ============================================================

def _gen_wav_bytes(duration_sec: float = 0.5, sr: int = 16000) -> bytes:
    n = int(sr * duration_sec)
    samples = []
    for i in range(n):
        if 0.3 * sr < i < 0.4 * sr:
            samples.append(0)
        else:
            samples.append(int(20000 * math.sin(2 * math.pi * 440 * i / sr)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{n}h", *samples))
    return buf.getvalue()


def _pcm_chunk(samples_count: int, sr: int = 16000) -> str:
    """生成一段 PCM bytes 并返回 base64"""
    samples = [10000 * (math.sin(2 * math.pi * 440 * i / sr) * 100) for i in range(samples_count)]
    samples = [max(-32768, min(32767, int(s))) for s in samples]
    pcm = struct.pack(f"<{samples_count}h", *samples)
    return base64.b64encode(pcm).decode("ascii")


# ============================================================
# StreamingASRSession
# ============================================================

def test_streaming_session_start():
    from audio_streaming import StreamingASRSession

    async def run():
        s = StreamingASRSession(session_id="test-1")
        ready = await s.handle_start({"type": "start", "lang": "zh"})
        assert ready["type"] == "ready"
        assert ready["session_id"] == "test-1"
        assert ready["lang"] == "zh"

    asyncio.run(run())


def test_streaming_session_audio_chunk():
    from audio_streaming import StreamingASRSession

    async def run():
        s = StreamingASRSession(session_id="test-2")
        await s.handle_start({"type": "start", "lang": "zh"})
        # 推 0.5s 音频（8000 样本 @ 16k）
        events = await s.handle_audio({
            "type": "audio", "data": _pcm_chunk(8000), "sample_rate": 16000
        })
        # 短段：<min_segment_ms 可能 flush 不到
        assert isinstance(events, list)

    asyncio.run(run())


def test_streaming_session_stop_flushes():
    from audio_streaming import StreamingASRSession

    async def run():
        s = StreamingASRSession(session_id="test-3")
        await s.handle_start({"type": "start", "lang": "zh"})
        # 推 1s 音频
        await s.handle_audio({
            "type": "audio", "data": _pcm_chunk(16000), "sample_rate": 16000
        })
        events = await s.handle_stop()
        assert any(e["type"] in ("final", "low_confidence") for e in events)
        assert any(e["type"] == "closed" for e in events)

    asyncio.run(run())


def test_streaming_session_double_start_resets():
    from audio_streaming import StreamingASRSession

    async def run():
        s = StreamingASRSession(session_id="test-4")
        await s.handle_start({"type": "start", "lang": "zh"})
        await s.handle_audio({"type": "audio", "data": _pcm_chunk(4000), "sample_rate": 16000})
        await s.handle_start({"type": "start", "lang": "en"})
        ready = s._lang
        assert ready == "en"
        assert len(s._buffer) == 0

    asyncio.run(run())


def test_streaming_invalid_base64_returns_error():
    from audio_streaming import StreamingASRSession

    async def run():
        s = StreamingASRSession(session_id="test-5")
        await s.handle_start({"type": "start"})
        events = await s.handle_audio({"type": "audio", "data": "not-base64@@"})
        assert any(e["type"] == "error" for e in events)

    asyncio.run(run())


# ============================================================
# LLMSemanticCorrector
# ============================================================

def test_semantic_corrector_no_llm_returns_input():
    from audio_semantic import LLMSemanticCorrector
    c = LLMSemanticCorrector(llm_callable=None, domain="AI")
    assert c.correct("打开 long chain 文档") == "打开 long chain 文档"


def test_semantic_corrector_with_mock_llm():
    from audio_semantic import LLMSemanticCorrector

    def mock_llm(prompt: str) -> str:
        assert "AI" in prompt  # domain 注入
        return "打开 LangChain 文档。"

    c = LLMSemanticCorrector(llm_callable=mock_llm, domain="AI")
    out = c.correct("打开 long chain 文档")
    assert out == "打开 LangChain 文档。"


def test_semantic_corrector_inject_context():
    from audio_semantic import LLMSemanticCorrector
    c = LLMSemanticCorrector(domain="AI Agent")
    out = c.inject_context(
        "打开 long chain",
        {"provider": "whisper_local", "confidence": 0.45, "hotwords_hit": ["LangChain"]},
    )
    assert "AI Agent" in out
    assert "whisper_local" in out
    assert "0.45" in out
    assert "LangChain" in out
    assert "打开 long chain" in out


def test_semantic_corrector_llm_failure_returns_input():
    from audio_semantic import LLMSemanticCorrector

    def bad_llm(prompt: str) -> str:
        raise RuntimeError("network error")

    c = LLMSemanticCorrector(llm_callable=bad_llm, domain="AI")
    assert c.correct("hello") == "hello"


# ============================================================
# AudioFeedbackStore
# ============================================================

def test_feedback_record_and_query(tmp_path):
    from audio_feedback import AudioFeedbackStore
    db = str(tmp_path / "test.db")
    store = AudioFeedbackStore(db_path=db)
    rid = store.record(
        session_id="s-1", attachment_id="a-1",
        original_text="打开 long chain", corrected_text="打开 LangChain",
        confidence=0.4, provider="whisper_local",
    )
    assert rid > 0
    rows = store.recent(limit=10)
    assert len(rows) == 1
    assert rows[0]["original_text"] == "打开 long chain"
    assert rows[0]["corrected_text"] == "打开 LangChain"
    assert rows[0]["confidence"] == 0.4
    assert rows[0]["provider"] == "whisper_local"


def test_feedback_stats(tmp_path):
    from audio_feedback import AudioFeedbackStore
    db = str(tmp_path / "test2.db")
    store = AudioFeedbackStore(db_path=db)
    store.record("s1", "a", "hello", "hello", 0.9, "whisper")
    store.record("s2", "b", "long chain", "LangChain", 0.3, "whisper")
    store.record("s3", "c", "支付宝", "支付宝", 0.95, "aliyun")
    s = store.stats()
    assert s["total"] == 3
    assert s["by_provider"]["whisper"] == 2
    assert s["by_provider"]["aliyun"] == 1
    assert 0 < s["avg_confidence"] < 1


def test_feedback_suggest_hotwords(tmp_path):
    from audio_feedback import AudioFeedbackStore
    db = str(tmp_path / "test3.db")
    store = AudioFeedbackStore(db_path=db)
    # 多次出现 LangChain
    for i in range(5):
        store.record("s", "a", "long chain", "LangChain", 0.5, "whisper")
    for i in range(2):
        store.record("s", "b", "open ai", "OpenAI", 0.6, "whisper")
    store.record("s", "c", "rust", "Rust", 0.7, "whisper")
    hw = store.suggest_hotwords(min_count=2)
    # LangChain 出现 5 次，OpenAI 2 次，Rust 1 次（不足阈值）
    assert "LangChain" in hw
    assert "OpenAI" in hw
    assert "Rust" not in hw


def test_feedback_by_session(tmp_path):
    from audio_feedback import AudioFeedbackStore
    db = str(tmp_path / "test4.db")
    store = AudioFeedbackStore(db_path=db)
    store.record("s1", "a", "x", "y", 0.5, "whisper")
    store.record("s2", "b", "x", "y", 0.5, "whisper")
    s1_rows = store.by_session("s1")
    assert len(s1_rows) == 1
    assert s1_rows[0]["session_id"] == "s1"


# ============================================================
# StreamingASRSession 集成 fallback
# ============================================================

def test_streaming_with_dummy_engine_marks_fallback():
    from audio_streaming import StreamingASRSession
    from audio_pipeline import AudioPipeline, AudioPipelineConfig, DummyEngine

    pipe = AudioPipeline(config=AudioPipelineConfig(default_provider="dummy"))
    pipe._engines = {"dummy": DummyEngine()}

    async def run():
        s = StreamingASRSession(session_id="test-d", pipeline=pipe)
        await s.handle_start({"type": "start", "lang": "zh"})
        # 1.5s 音频
        await s.handle_audio({"type": "audio", "data": _pcm_chunk(24000), "sample_rate": 16000})
        events = await s.handle_stop()
        # final 或 low_confidence 二选一
        final_events = [e for e in events if e.get("type") in ("final", "low_confidence")]
        assert len(final_events) >= 1
        ev = final_events[0]
        assert ev["fallback_used"] is True
        assert ev["provider"] == "dummy"

    asyncio.run(run())
