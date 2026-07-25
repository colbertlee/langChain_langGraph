"""
语音流式识别（Streaming ASR）

提供：
- StreamingASRSession：单次 WebSocket 会话的 ASR 状态机
  - 接收 PCM chunk（16k / 16bit / mono）
  - 累积 buffer + VAD 端点检测
  - 检测到一句话后立即调 ASR 引擎
  - 推送 partial / final 文本
- 与 audio_pipeline 复用：底层调用同一套 ASR 引擎 + 预处理 + 纠错
- 依赖缺失时降级到 dummy

客户端协议（JSON）：
  接收：
    { "type": "start", "lang": "zh", "provider": "whisper_local", "session_id": "..." }
    { "type": "audio", "data": "<base64 PCM>", "sample_rate": 16000 }
    { "type": "stop" }
  推送：
    { "type": "ready", "session_id": "..." }
    { "type": "partial", "text": "...", "ts": 0.0 }       # 边录边识别（可选）
    { "type": "final",   "text": "...", "confidence": 0.9, "provider": "whisper_local",
                          "fallback_used": false, "hotwords_hit": [...], "t_start": 0.0, "t_end": 1.2 }
    { "type": "low_confidence", "text": "...", "confidence": 0.4, "session_id": "..." }  # 触发前端确认
    { "type": "error", "error": "..." }
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
import wave
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from audio_pipeline import (
    AudioPipeline,
    AudioPipelineConfig,
    AudioPreprocessor,
    ConfidenceGate,
    HotwordCorrector,
    get_audio_pipeline,
)

logger = logging.getLogger(__name__)


@dataclass
class StreamSegment:
    """一段累积的音频（包含起止时间戳）"""
    pcm: bytearray = field(default_factory=bytearray)
    sample_rate: int = 16000
    start_ts: float = 0.0
    last_ts: float = 0.0
    emitted: bool = False

    @property
    def duration_sec(self) -> float:
        n = len(self.pcm) // 2
        return n / max(self.sample_rate, 1)


class StreamingASRSession:
    """单次 WebSocket 会话的 ASR 状态机。"""

    def __init__(
        self,
        pipeline: Optional[AudioPipeline] = None,
        config: Optional[AudioPipelineConfig] = None,
        session_id: str = "",
        max_segment_seconds: int = 30,
        silence_trigger_ms: int = 700,
        min_segment_ms: int = 300,
    ):
        self.pipeline = pipeline or get_audio_pipeline()
        self.config = config or self.pipeline.config
        self.session_id = session_id
        self.max_segment_seconds = max_segment_seconds
        self.silence_trigger_ms = silence_trigger_ms
        self.min_segment_ms = min_segment_ms

        self._pre = AudioPreprocessor()
        self._corrector = HotwordCorrector(self.config.hotwords)
        self._gate = ConfidenceGate(self.config.confidence_threshold)

        self._buffer = bytearray()
        self._sample_rate = 16000
        self._last_voice_ts: Optional[float] = None
        self._segment_start_ts: float = 0.0
        self._started_at: Optional[float] = None
        self._lang: str = self.config.default_lang
        self._provider: Optional[str] = None
        self._closed = False

    # --------------------------------------------------------
    # 客户端消息处理
    # --------------------------------------------------------

    async def handle_start(self, msg: Dict[str, Any]) -> Dict[str, Any]:
        self._lang = msg.get("lang", self.config.default_lang) or self.config.default_lang
        self._provider = msg.get("provider") or None
        self._session_id = msg.get("session_id") or self.session_id
        self._started_at = time.time()
        self._buffer = bytearray()
        self._last_voice_ts = None
        self._segment_start_ts = 0.0
        return {
            "type": "ready",
            "session_id": self._session_id,
            "sample_rate": self._sample_rate,
            "lang": self._lang,
        }

    async def handle_audio(self, msg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        接收一段 audio chunk，返回要推送的事件列表（可能含 0 个 final）。
        """
        if self._closed:
            return [{"type": "error", "error": "session closed"}]

        b64 = msg.get("data")
        if not b64:
            return [{"type": "error", "error": "empty audio data"}]
        try:
            raw = base64.b64decode(b64)
        except Exception as e:  # noqa: BLE001
            return [{"type": "error", "error": f"base64 decode: {e}"}]

        # 客户端可声明 sample_rate；默认 16k
        sr = int(msg.get("sample_rate") or self._sample_rate)
        self._sample_rate = sr

        # 累积到 buffer
        self._buffer.extend(raw)

        # 切分判断：VAD 端点检测 + 最大段长度
        events: List[Dict[str, Any]] = []
        now = time.time()
        if self._started_at is None:
            self._started_at = now

        # 简化：当累积时长超过 max_segment_seconds 强制切分
        total_sec = len(self._buffer) / 2 / max(sr, 1)
        if total_sec >= self.max_segment_seconds:
            ev = await self._flush_segment(reason="max_segment")
            if ev:
                events.append(ev)
        return events

    async def handle_stop(self) -> List[Dict[str, Any]]:
        """客户端发送 stop，把剩余 buffer 识别为最后一段。"""
        events: List[Dict[str, Any]] = []
        if self._buffer:
            ev = await self._flush_segment(reason="stop")
            if ev:
                if isinstance(ev, list):
                    events.extend(ev)
                else:
                    events.append(ev)
        self._closed = True
        events.append({"type": "closed", "session_id": self.session_id})
        return events

    # --------------------------------------------------------
    # 内部：VAD 切分 + ASR
    # --------------------------------------------------------

    async def _flush_segment(self, reason: str = "") -> Optional[Dict[str, Any]]:
        """识别当前累积 buffer，生成 final 事件并清空 buffer。"""
        if not self._buffer:
            return None
        pcm = bytes(self._buffer)
        self._buffer = bytearray()
        sr = self._sample_rate

        # 用 VAD 二次切分（短句可能直接整段）
        segs = self._pre.vad_segments(
            pcm, sr,
            max_segment_seconds=self.max_segment_seconds,
        )

        # 串行处理每段（faster-whisper 不支持并发）
        text_parts: List[str] = []
        confidences: List[float] = []
        last_provider = self._provider or self.config.default_provider
        hotwords_hit: List[str] = []
        first_error: Optional[str] = None
        for seg_pcm, t_start, t_end in segs:
            # 短段（<100ms）跳过
            if (t_end - t_start) * 1000 < 80:
                continue
            r = await asyncio.to_thread(
                self._transcribe_segment, seg_pcm, sr, self._lang, last_provider
            )
            if r.get("error") and not first_error:
                first_error = r["error"]
            if r.get("text"):
                text_parts.append(r["text"])
            if r.get("confidence"):
                confidences.append(r["confidence"])
            last_provider = r.get("provider", last_provider)
            hotwords_hit.extend(r.get("hotwords_hit", []))

        merged_text = "".join(text_parts).strip()
        confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # 纠错
        if self.config.enable_correction and merged_text:
            merged_text = self._corrector.correct(merged_text, hit_out=hotwords_hit)

        fallback = False
        if self.config.enable_confidence_gate:
            if not merged_text or len(merged_text.strip()) <= 1:
                fallback = True
            elif confidence < self.config.confidence_threshold:
                fallback = True

        event: Dict[str, Any] = {
            "type": "final",
            "text": merged_text,
            "confidence": confidence,
            "provider": last_provider,
            "lang": self._lang,
            "fallback_used": fallback,
            "hotwords_hit": list(set(hotwords_hit)),
            "reason": reason,
            "session_id": self.session_id,
        }
        if first_error:
            event["error"] = first_error

        # 触发低置信度提示
        if fallback:
            event2 = {
                "type": "low_confidence",
                "text": merged_text,
                "confidence": confidence,
                "session_id": self.session_id,
            }
            # 主事件 + 触发事件都推
            return [event, event2]
        return event

    async def _flush_segment_single(self) -> Optional[Dict[str, Any]]:
        """对外只返回单一 dict（取最后一个事件）。"""
        ev = await self._flush_segment(reason="")
        if isinstance(ev, list):
            return ev[-1] if ev else None
        return ev

    def _transcribe_segment(
        self,
        pcm: bytes,
        sample_rate: int,
        lang: str,
        provider: Optional[str],
    ) -> Dict[str, Any]:
        """调用底层 ASR engine（同步）。"""
        from audio_pipeline import DummyEngine

        engine = self.pipeline._pick_engine(provider or self.config.default_provider)
        result = engine.transcribe(pcm, sample_rate, lang, self.config.hotwords)
        return {
            "text": result.text,
            "confidence": result.confidence,
            "provider": result.provider,
            "hotwords_hit": result.hotwords_hit,
            "error": result.error,
        }


# ============================================================
# 工具：WAV 字节 → PCM
# ============================================================

def wav_to_pcm(wav_bytes: bytes) -> tuple[bytes, int]:
    """解码 WAV 字节到 (pcm_bytes, sample_rate)。"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
        sr = wf.getframerate()
        sw = wf.getsampwidth()
        ch = wf.getnchannels()
        raw = wf.readframes(wf.getnframes())
    if sw != 2 or ch != 1:
        # 简化：仅支持 16k / 16bit / mono；其他格式原样返回 + 标记
        return raw, sr
    return raw, sr


def pcm_to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()
