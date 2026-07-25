"""
AudioPipeline 单元测试（不依赖真实 ASR 服务）。

覆盖：
1. WAV 解码 + 元信息
2. 降噪 / AGC
3. VAD 切分
4. 热词纠错（编辑距离）
5. DummyEngine 兜底
6. 主流水线走通（无 Whisper/无外部服务时返回空文本 + fallback_used=True）
7. 与 multimodal.Attachment 集成
"""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest


# ============================================================
# 工具：生成测试用 WAV
# ============================================================

def _gen_wav(duration_sec: float = 1.0, sr: int = 16000, freq: float = 440.0) -> bytes:
    n = int(sr * duration_sec)
    samples = []
    for i in range(n):
        # 0.3s 处静音，其余正弦波（模拟"中间有停顿"）
        if 0.3 * sr < i < 0.5 * sr:
            samples.append(0)
        else:
            samples.append(int(20000 * math.sin(2 * math.pi * freq * i / sr)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack(f"<{n}h", *samples))
    return buf.getvalue()


# ============================================================
# 单元测试
# ============================================================

def test_decode_wav_basic():
    from audio_pipeline import AudioPreprocessor

    data = _gen_wav(0.5)
    pcm, meta = AudioPreprocessor.decode_wav(data)
    assert meta.sample_rate == 16000
    assert meta.channels == 1
    assert meta.sample_width == 2
    assert 0.4 < meta.duration_sec < 0.6
    assert len(pcm) > 0


def test_denoise_agc_increases_peak():
    from audio_pipeline import AudioPreprocessor

    # 主体信号 5000 + 前 0.2s 静音（用于估计噪声）
    n = 16000
    samples = [0] * (16000 // 5) + [5000] * (n - 16000 // 5)
    pcm = struct.pack(f"<{n}h", *samples)
    out = AudioPreprocessor.denoise_and_agc(pcm, sample_rate=16000)
    out_samples = struct.unpack(f"<{n}h", out)
    # 主体段被放大、静音段被清零
    body = out_samples[16000 // 5 :]
    assert max(abs(s) for s in body) >= 20000
    silence = out_samples[: 16000 // 5]
    assert max(abs(s) for s in silence) == 0


def test_vad_segments_finds_speech():
    from audio_pipeline import AudioPreprocessor

    data = _gen_wav(duration_sec=1.0)
    pcm, meta = AudioPreprocessor.decode_wav(data)
    pre = AudioPreprocessor()
    segs = pre.vad_segments(pcm, meta.sample_rate, max_segment_seconds=30)
    assert len(segs) >= 1
    # 第一段和最后一段的时长在合理范围
    s, start, end = segs[0]
    assert end > start


def test_hotword_corrector_edit_distance():
    from audio_pipeline import HotwordCorrector

    # 距离 1 的错词被纠正
    c = HotwordCorrector(hotwords=["LangChain", "LangGraph", "OpenAI"])
    hit = []
    out = c.correct("请使用 Langhain 和 LangGrap", hit_out=hit)
    assert "LangChain" in out
    assert "LangGraph" in out
    # 原始错词不应以"独立单词"形式存在（注意 LangGrap 是 LangGraph 的子串）
    assert " Langhain" not in out
    assert out.endswith("LangGraph")
    assert set(hit) >= {"LangChain", "LangGraph"}


def test_hotword_corrector_homophone_map():
    from audio_pipeline import HotwordCorrector

    c = HotwordCorrector(homophone_map={"支护宝": "支付宝"})
    assert c.correct("我用支护宝付款") == "我用支付宝付款"


def test_pipeline_fallback_when_no_engine():
    """没有任何 ASR 引擎时，必须返回 fallback_used=True 而不是抛异常"""
    from audio_pipeline import (
        AudioPipeline, AudioPipelineConfig, DummyEngine,
    )

    cfg = AudioPipelineConfig(default_provider="dummy")
    pipe = AudioPipeline(config=cfg)
    # 强制只留 dummy
    pipe._engines = {"dummy": DummyEngine()}

    data = _gen_wav(0.5)
    result = pipe.transcribe_bytes(data, mime="audio/wav")
    assert result.fallback_used is True
    assert result.error is not None
    assert result.provider == "dummy"


def test_integration_with_multimodal_attachment():
    """通过 multimodal.Attachment 走完整管线"""
    from multimodal import Attachment, Modality, AttachmentProcessor
    from audio_pipeline import get_audio_pipeline, reset_audio_pipeline

    reset_audio_pipeline()
    pipe = get_audio_pipeline()
    pipe._engines = {"dummy": pipe._engines["dummy"]}  # 强制 fallback

    att = Attachment.from_file.__func__  # noqa: just touch
    import tempfile, os
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.write(_gen_wav(0.5))
    tmp.close()
    try:
        from multimodal import Attachment
        att = Attachment.from_file(tmp.name, source="test")
        assert att.modality == Modality.AUDIO

        proc = AttachmentProcessor()
        text = _run_async(proc.process(att))
        # 没真实 ASR → 拿不到文字，但必须不抛异常
        assert isinstance(text, str)
        # metadata 里应记录了 ASR provider
        assert "asr_provider" in (att.metadata or {})
    finally:
        os.unlink(tmp.name)


def _run_async(coro):
    import asyncio
    return asyncio.run(coro)


def test_edit_distance_basic():
    from audio_pipeline import _edit_distance
    assert _edit_distance("abc", "abc") == 0
    assert _edit_distance("abc", "abcd") == 1
    assert _edit_distance("kitten", "sitting") == 3
