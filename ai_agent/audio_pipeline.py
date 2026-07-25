"""
语音输入管线（Audio Pipeline）

目标：把音频附件（Modality.AUDIO）稳定、准确地转成文本，再交给上层 LLM。

设计原则（与项目一致）：
1. 防御性降级：依赖缺失时走兜底分支，不抛未捕获异常。
2. 单一真相源：依 provider 路由落到具体 ASR 实现，热词 / 上下文 / 后处理都集中配置。
3. 职责分离：preprocess -> asr -> postprocess -> confidence_gate 四步流水线，互不耦合。
4. 最小依赖：默认仅用标准库 + httpx；Whisper / 阿里云 / 讯飞作为可选后端。

提供：
- AudioPreprocessor：降噪 / 自动增益 / VAD 端点检测 / 切分长音频
- ASREngine 抽象 + 三个实现：WhisperLocalEngine / AliyunEngine / IflytekEngine
- HotwordCorrector：基于词表 + 编辑距离的纠错（针对同音字 / 术语）
- ConfidenceGate：低置信度兜底（返回多候选 / 触发人工确认）
- AudioPipeline：对外主入口，对应 multimodal.py 中 _default_audio_transcriber 的位置

使用：
    from audio_pipeline import get_audio_pipeline
    pipeline = get_audio_pipeline()
    text, meta = pipeline.transcribe(att)
    # meta 包含: provider, confidence, lang, duration_sec, candidates, ...
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import struct
import time
import wave
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# 配置
# ============================================================

@dataclass
class AudioPipelineConfig:
    """管线配置（可被环境变量覆盖）"""
    # 默认 ASR provider: whisper_local | aliyun | iflytek | dummy
    default_provider: str = field(
        default_factory=lambda: os.getenv("AUDIO_ASR_PROVIDER", "whisper_local")
    )
    # 默认语言: zh / en / auto
    default_lang: str = field(default_factory=lambda: os.getenv("AUDIO_LANG", "zh"))
    # Whisper 本地模型名（越大的越准但越慢）
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "base"))
    # 阿里云 AppKey / Token
    aliyun_token: str = field(default_factory=lambda: os.getenv("ALIYUN_ASR_TOKEN", ""))
    aliyun_appkey: str = field(default_factory=lambda: os.getenv("ALIYUN_ASR_APPKEY", ""))
    # 讯飞 APPID / APIKey / APISecret
    iflytek_app_id: str = field(default_factory=lambda: os.getenv("IFLYTEK_APP_ID", ""))
    iflytek_api_key: str = field(default_factory=lambda: os.getenv("IFLYTEK_API_KEY", ""))
    iflytek_api_secret: str = field(default_factory=lambda: os.getenv("IFLYTEK_API_SECRET", ""))
    # 切分长音频的最大秒数（避免一次性送 Whisper 触发 OOM）
    max_segment_seconds: int = 30
    # 置信度阈值：低于此值做兜底
    confidence_threshold: float = 0.6
    # 热词 / 领域术语
    hotwords: List[str] = field(
        default_factory=lambda: _split_env("AUDIO_HOTWORDS")
    )
    # 领域上下文（用于后处理 prompt）
    domain_context: str = field(default_factory=lambda: os.getenv("AUDIO_DOMAIN_CONTEXT", ""))
    # 启用音频预处理（降噪 / AGC / VAD）
    enable_preprocess: bool = True
    # 启用纠错
    enable_correction: bool = True
    # 启用置信度兜底
    enable_confidence_gate: bool = True
    # 启用 LLM 语义纠错（依赖 langchain OpenAI 等）
    enable_semantic_correction: bool = field(
        default_factory=lambda: os.getenv("AUDIO_ENABLE_LLM_CORRECTION", "false").lower() == "true"
    )


def _split_env(name: str) -> List[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [w.strip() for w in raw.split(",") if w.strip()]


# ============================================================
# 数据类型
# ============================================================

@dataclass
class AudioMeta:
    """音频文件元信息"""
    sample_rate: int = 0
    sample_width: int = 0  # bytes per sample
    channels: int = 0
    duration_sec: float = 0.0
    size_bytes: int = 0


@dataclass
class TranscriptionResult:
    """转录结果"""
    text: str
    confidence: float = 0.0
    provider: str = "unknown"
    lang: str = ""
    duration_sec: float = 0.0
    candidates: List[Tuple[str, float]] = field(default_factory=list)
    hotwords_hit: List[str] = field(default_factory=list)
    fallback_used: bool = False
    error: Optional[str] = None
    debug: Dict[str, Any] = field(default_factory=dict)


# ============================================================
# 音频预处理
# ============================================================

class AudioPreprocessor:
    """
    轻量预处理：
    - 解码 WAV 头（PCM），其他格式透传
    - 自动增益（peak normalize）
    - VAD 端点检测：
        - 优先 webrtcvad（更准，需 pywebrtcvad）
        - 降级 RMS 能量（纯 stdlib）
    - 切分长音频
    """

    def __init__(self, prefer_webrtcvad: bool = True):
        self.webrtcvad = None
        self._webrtcvad_error: Optional[str] = None
        if prefer_webrtcvad:
            try:
                import webrtcvad  # type: ignore
                self.webrtcvad = webrtcvad.Vad(2)  # 0-3，2 适中
                logger.info("[AudioPreprocessor] webrtcvad enabled")
            except Exception as e:  # noqa: BLE001
                self._webrtcvad_error = str(e)
                logger.info(f"[AudioPreprocessor] webrtcvad unavailable, fallback to RMS: {e}")

    @staticmethod
    def decode_wav(data: bytes) -> Tuple[bytes, AudioMeta]:
        """尝试把 WAV 字节解码成 16-bit PCM mono，返回 (pcm_bytes, meta)"""
        meta = AudioMeta(size_bytes=len(data))
        try:
            with wave.open(io.BytesIO(data), "rb") as wf:
                meta.channels = wf.getnchannels()
                meta.sample_width = wf.getsampwidth()
                meta.sample_rate = wf.getframerate()
                meta.duration_sec = wf.getnframes() / max(meta.sample_rate, 1)
                raw = wf.readframes(wf.getnframes())
        except (wave.Error, EOFError, struct.error) as e:
            logger.debug(f"decode_wav failed, treat as raw: {e}")
            return data, meta

        # 转为 mono + 16-bit
        if meta.channels > 1:
            raw = AudioPreprocessor._to_mono(raw, meta.channels, meta.sample_width)
            meta.channels = 1
        if meta.sample_width != 2:
            raw = AudioPreprocessor._to_int16(raw, meta.sample_width)
            meta.sample_width = 2
        return raw, meta

    @staticmethod
    def _to_mono(raw: bytes, channels: int, sample_width: int) -> bytes:
        if sample_width == 2:
            samples = struct.unpack(f"<{len(raw) // 2}h", raw)
            step = channels
            out = []
            for i in range(0, len(samples), step):
                chunk = samples[i:i + step]
                out.append(sum(chunk) // len(chunk))
            return struct.pack(f"<{len(out)}h", *out)
        # 其它位宽：直接取第 0 通道
        return raw[::channels]

    @staticmethod
    def _to_int16(raw: bytes, sample_width: int) -> bytes:
        if sample_width == 1:
            return b"".join(bytes([(b - 128) * 256]) for b in raw)
        if sample_width == 4:
            samples = struct.unpack(f"<{len(raw) // 4}i", raw)
            return struct.pack(f"<{len(samples)}h", *(max(-32768, min(32767, s >> 16)) for s in samples))
        return raw

    @staticmethod
    def denoise_and_agc(
        pcm: bytes,
        sample_rate: int,
        denoise_strength: float = 0.15,
        target_peak: int = 28000,
    ) -> bytes:
        """降噪 + 自动增益（轻量版，运行极快）"""
        if not pcm or sample_rate <= 0:
            return pcm
        n = len(pcm) // 2
        if n == 0:
            return pcm
        samples = struct.unpack(f"<{n}h", pcm)

        # 估计噪声 floor：用最安静的 10% 帧的均值
        frame_size = max(1, sample_rate // 50)  # 20ms
        frame_rms = []
        for i in range(0, n, frame_size):
            chunk = samples[i:i + frame_size]
            if not chunk:
                continue
            ms = sum(s * s for s in chunk) / len(chunk)
            frame_rms.append(math.sqrt(ms))
        if not frame_rms:
            return pcm
        frame_rms_sorted = sorted(frame_rms)
        quiet = frame_rms_sorted[: max(1, len(frame_rms_sorted) // 10)]
        noise_floor = sum(quiet) / len(quiet)

        # 自动增益因子
        peak = max(abs(s) for s in samples) or 1
        gain = target_peak / peak
        gain = max(0.5, min(gain, 4.0))  # 限制在 0.5x ~ 4x

        # 阈值：噪声 floor + 一定冗余
        threshold = noise_floor * (1.0 + denoise_strength) + 1.0

        out = []
        for s in samples:
            # 降噪：低于阈值视为噪声
            if abs(s) < threshold:
                s = 0
            # AGC
            v = int(s * gain)
            if v > 32767:
                v = 32767
            elif v < -32768:
                v = -32768
            out.append(v)
        return struct.pack(f"<{len(out)}h", *out)

    def vad_segments(
        self,
        pcm: bytes,
        sample_rate: int,
        frame_ms: int = 30,
        threshold_ratio: float = 0.02,
        min_speech_ms: int = 250,
        max_segment_seconds: int = 30,
    ) -> List[Tuple[bytes, float, float]]:
        """
        VAD 端点检测 + 切分。
        - 优先 webrtcvad（实例方法调用）
        - 降级 RMS 能量
        """
        if not pcm or sample_rate <= 0:
            return [(pcm, 0.0, 0.0)]
        if self.webrtcvad is not None and sample_rate in (8000, 16000, 32000, 48000):
            return self._vad_webrtc(pcm, sample_rate, frame_ms, max_segment_seconds)
        return self._vad_rms(
            pcm, sample_rate, frame_ms, threshold_ratio, min_speech_ms, max_segment_seconds
        )

    def _vad_webrtc(
        self,
        pcm: bytes,
        sample_rate: int,
        frame_ms: int,
        max_segment_seconds: int,
    ) -> List[Tuple[bytes, float, float]]:
        """webrtcvad 版：按帧判断语音/静音，组装段落"""
        n = len(pcm) // 2
        frame_size = sample_rate * frame_ms // 1000 * 2  # bytes
        if frame_size <= 0:
            return [(pcm, 0.0, n / max(sample_rate, 1))]
        max_segment_bytes = sample_rate * max_segment_seconds * 2

        segments: List[Tuple[bytes, float, float]] = []
        cur_start_frame: Optional[int] = None
        cur_len_bytes = 0
        for i in range(0, len(pcm), frame_size):
            chunk = pcm[i:i + frame_size]
            if len(chunk) < frame_size:
                # 末尾不完整帧：跳过（或并入前一段）
                if cur_start_frame is not None:
                    cur_len_bytes += len(chunk)
                continue
            try:
                is_speech = self.webrtcvad.is_speech(chunk, sample_rate)
            except Exception:
                is_speech = False
            if is_speech:
                if cur_start_frame is None:
                    cur_start_frame = i
                    cur_len_bytes = 0
                cur_len_bytes += frame_size
            else:
                if cur_start_frame is not None and cur_len_bytes >= frame_size * 3:
                    seg_pcm = pcm[cur_start_frame: cur_start_frame + cur_len_bytes]
                    start_sec = cur_start_frame / 2 / sample_rate
                    end_sec = (cur_start_frame + cur_len_bytes) / 2 / sample_rate
                    segments.append((seg_pcm, start_sec, end_sec))
                    cur_start_frame = None
                    cur_len_bytes = 0
            # 切分超长段
            if cur_start_frame is not None and cur_len_bytes >= max_segment_bytes:
                seg_pcm = pcm[cur_start_frame: cur_start_frame + cur_len_bytes]
                start_sec = cur_start_frame / 2 / sample_rate
                end_sec = (cur_start_frame + cur_len_bytes) / 2 / sample_rate
                segments.append((seg_pcm, start_sec, end_sec))
                cur_start_frame = None
                cur_len_bytes = 0
        # 收尾
        if cur_start_frame is not None and cur_len_bytes > 0:
            seg_pcm = pcm[cur_start_frame: cur_start_frame + cur_len_bytes]
            start_sec = cur_start_frame / 2 / sample_rate
            end_sec = (cur_start_frame + cur_len_bytes) / 2 / sample_rate
            segments.append((seg_pcm, start_sec, end_sec))
        if not segments:
            return [(pcm, 0.0, n / max(sample_rate, 1))]
        return segments

    @staticmethod
    def _vad_rms(
        pcm: bytes,
        sample_rate: int,
        frame_ms: int,
        threshold_ratio: float,
        min_speech_ms: int,
        max_segment_seconds: int,
    ) -> List[Tuple[bytes, float, float]]:
        """RMS-based VAD（兜底实现）"""
        if not pcm or sample_rate <= 0:
            return [(pcm, 0.0, 0.0)]
        n = len(pcm) // 2
        frame_size = max(1, sample_rate * frame_ms // 1000)
        if frame_size <= 0:
            return [(pcm, 0.0, 0.0)]

        samples = struct.unpack(f"<{n}h", pcm)
        # 计算每帧 RMS
        rms_list: List[float] = []
        for i in range(0, n, frame_size):
            chunk = samples[i:i + frame_size]
            if not chunk:
                continue
            ms = sum(s * s for s in chunk) / len(chunk)
            rms_list.append(math.sqrt(ms))

        if not rms_list:
            return [(pcm, 0.0, 0.0)]
        # 动态阈值：基于最大 RMS 的比例
        peak_rms = max(rms_list) or 1.0
        threshold = peak_rms * threshold_ratio

        # 标记语音帧
        min_speech_frames = max(1, min_speech_ms // frame_ms)
        max_segment_frames = max(1, int(max_segment_seconds * 1000 / frame_ms))

        segments: List[Tuple[bytes, float, float]] = []
        cur_start: Optional[int] = None
        cur_len = 0

        def flush(end_frame: int):
            nonlocal cur_start, cur_len
            if cur_start is None or cur_len == 0:
                cur_start = None
                cur_len = 0
                return
            s = cur_start
            e = cur_start + cur_len
            start_sec = s * frame_ms / 1000.0
            end_sec = e * frame_ms / 1000.0
            seg_samples = samples[s * frame_size: e * frame_size]
            if seg_samples:
                segments.append((
                    struct.pack(f"<{len(seg_samples)}h", *seg_samples),
                    start_sec,
                    end_sec,
                ))
            cur_start = None
            cur_len = 0

        for i, r in enumerate(rms_list):
            is_speech = r >= threshold
            if is_speech:
                if cur_start is None:
                    cur_start = i
                    cur_len = 1
                else:
                    cur_len += 1
                # 切分过长段
                if cur_len >= max_segment_frames:
                    flush(i + 1)
            else:
                # 短停顿：保留，连续 N 帧静音再 flush
                if cur_start is not None and cur_len >= min_speech_frames:
                    flush(i)
        flush(len(rms_list))

        if not segments:
            # 没检测到语音：返回原音频
            return [(pcm, 0.0, n / max(sample_rate, 1))]
        return segments


# ============================================================
# ASR 引擎抽象
# ============================================================

class ASREngine:
    """ASR 引擎基类"""

    name: str = "base"

    def transcribe(
        self,
        pcm: bytes,
        sample_rate: int,
        lang: str,
        hotwords: List[str],
    ) -> TranscriptionResult:
        raise NotImplementedError


class DummyEngine(ASREngine):
    """占位引擎：依赖缺失时降级用。返回带文件名提示的字符串，便于排查。"""

    name = "dummy"

    def transcribe(self, pcm, sample_rate, lang, hotwords):
        return TranscriptionResult(
            text="",
            confidence=0.0,
            provider=self.name,
            lang=lang,
            duration_sec=0.0,
            fallback_used=True,
            error="no ASR engine available",
        )


class WhisperLocalEngine(ASREngine):
    """
    基于 faster-whisper 的本地 ASR（兼容 openai-whisper 的 .transcribe）。
    依赖缺失时自动降级为 DummyEngine。
    """

    name = "whisper_local"

    def __init__(self, model_name: str = "base"):
        self.model_name = model_name
        self._model = None
        self._init_error: Optional[str] = None
        self._init_model()

    def _init_model(self):
        try:
            from faster_whisper import WhisperModel  # type: ignore
            self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
            logger.info(f"[Whisper] loaded model={self.model_name}")
        except Exception as e:  # noqa: BLE001
            self._init_error = str(e)
            logger.warning(f"[Whisper] init failed, fall back to dummy: {e}")
            try:
                import whisper  # type: ignore
                self._model = whisper.load_model(self.model_name)
                logger.info(f"[Whisper/openai] loaded model={self.model_name}")
            except Exception as e2:  # noqa: BLE001
                self._init_error = f"faster-whisper: {e}; openai-whisper: {e2}"
                self._model = None

    def transcribe(self, pcm, sample_rate, lang, hotwords):
        if self._model is None:
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error=self._init_error or "whisper not available",
            )

        # 写到临时 WAV（faster-whisper / whisper 接受文件名或 numpy）
        import tempfile
        try:
            import numpy as np  # type: ignore
        except Exception:
            np = None  # type: ignore

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                tmp_path = f.name
                with wave.open(f, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(pcm)

            try:
                if hasattr(self._model, "transcribe") and not callable(getattr(self._model, "decode", None)):
                    # faster-whisper
                    initial_prompt = " ".join(hotwords) if hotwords else None
                    segments, info = self._model.transcribe(
                        tmp_path,
                        language=lang if lang in ("zh", "en", "ja", "ko") else None,
                        beam_size=5,
                        vad_filter=True,
                        initial_prompt=initial_prompt,
                    )
                    text = "".join(seg.text for seg in segments).strip()
                    # faster-whisper 没有逐段 confidence，用分段数做粗估
                    confidence = 0.85
                    used_lang = getattr(info, "language", lang) or lang
                else:
                    # openai-whisper
                    result = self._model.transcribe(
                        tmp_path,
                        language=lang if lang in ("zh", "en", "ja", "ko") else None,
                        initial_prompt=" ".join(hotwords) if hotwords else None,
                    )
                    text = (result.get("text") or "").strip()
                    confidence = 0.8
                    used_lang = result.get("language", lang) or lang
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

            return TranscriptionResult(
                text=text,
                confidence=confidence,
                provider=self.name,
                lang=used_lang,
                candidates=[(text, confidence)],
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[Whisper] transcribe failed: {e}")
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error=str(e),
            )


class AliyunEngine(ASREngine):
    """
    阿里云一句话识别 REST 接口（非流式）。
    文档：https://help.aliyun.com/zh/isi/getting-started/restful-api-for-short-text-to-speech
    依赖：ALIYUN_ASR_TOKEN（已含 AppKey 的方式）或 AppKey + 临时 Token。
    """

    name = "aliyun"

    HOST = "https://openspeech.bytedance.com/api/v1/asr"
    # 实际阿里云一句话识别 host 需按 region 调整；保留占位默认
    REAL_HOST = "https://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/asr"

    def __init__(self, appkey: str, token: str):
        self.appkey = appkey
        self.token = token

    def _is_ready(self) -> bool:
        return bool(self.appkey and self.token)

    def transcribe(self, pcm, sample_rate, lang, hotwords):
        if not self._is_ready():
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error="aliyun credentials missing",
            )
        try:
            import httpx  # type: ignore
        except Exception:
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error="httpx not installed",
            )

        fmt = "pcm"
        url = (
            f"{self.REAL_HOST}?appkey={self.appkey}&format={fmt}"
            f"&sample_rate={sample_rate}&language={lang or 'zh'}"
        )
        headers = {
            "X-NLS-Token": self.token,
            "Content-Type": "application/octet-stream",
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, content=pcm, headers=headers)
            if resp.status_code != 200:
                return TranscriptionResult(
                    text="",
                    confidence=0.0,
                    provider=self.name,
                    lang=lang,
                    fallback_used=True,
                    error=f"http {resp.status_code}: {resp.text[:200]}",
                )
            data = resp.json()
            # 阿里云返回结构：{"result":"...", "status":200, "message":"..."}
            text = (data.get("result") or "").strip()
            if not text:
                return TranscriptionResult(
                    text="",
                    confidence=0.0,
                    provider=self.name,
                    lang=lang,
                    fallback_used=True,
                    error=f"empty result: {data}",
                )
            return TranscriptionResult(
                text=text,
                confidence=0.9,
                provider=self.name,
                lang=lang,
                candidates=[(text, 0.9)],
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[Aliyun] transcribe failed: {e}")
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error=str(e),
            )


class IflytekEngine(ASREngine):
    """
    讯飞一句话识别 REST 版（基于 WebAPI / 简易签名）。
    占位实现：依赖环境变量齐全时调用短语音接口，否则 fallback。
    """

    name = "iflytek"

    HOST = "https://api-dx.xf-yun.com/v1/private/dts_create"

    def __init__(self, app_id: str, api_key: str, api_secret: str):
        self.app_id = app_id
        self.api_key = api_key
        self.api_secret = api_secret

    def _is_ready(self) -> bool:
        return bool(self.app_id and self.api_key and self.api_secret)

    def transcribe(self, pcm, sample_rate, lang, hotwords):
        if not self._is_ready():
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error="iflytek credentials missing",
            )
        try:
            import httpx  # type: ignore
        except Exception:
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error="httpx not installed",
            )

        # 简化：使用 base64 内嵌到 JSON 体（不同讯飞接口字段不同，按需调整）
        audio_b64 = _b64(pcm)
        body = {
            "header": {"app_id": self.app_id, "status": 3},
            "parameter": {
                "dts": {
                    "lang": "cn" if lang.startswith("zh") else "en",
                    "accent": "mandarin",
                    "domain": "iat",
                    "vad_eos": 1500,
                }
            },
            "payload": {
                "audio": {"audio": audio_b64, "sample_rate": sample_rate, "encoding": "raw"},
            },
        }
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(self.HOST, json=body)
            if resp.status_code != 200:
                return TranscriptionResult(
                    text="",
                    confidence=0.0,
                    provider=self.name,
                    lang=lang,
                    fallback_used=True,
                    error=f"http {resp.status_code}: {resp.text[:200]}",
                )
            data = resp.json()
            # 解析讯飞返回：payload.out.texts[]
            text = ""
            try:
                texts = data["payload"]["out"]["texts"]
                text = "".join(t.get("text", "") for t in texts)
            except (KeyError, TypeError):
                text = ""
            return TranscriptionResult(
                text=text.strip(),
                confidence=0.9,
                provider=self.name,
                lang=lang,
                candidates=[(text, 0.9)],
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[Iflytek] transcribe failed: {e}")
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider=self.name,
                lang=lang,
                fallback_used=True,
                error=str(e),
            )


def _b64(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode("ascii")


# ============================================================
# 纠错 / 置信度兜底
# ============================================================

class HotwordCorrector:
    """
    基于热词表的轻量纠错：
    1. 数字 / 英文术语大小写标准化
    2. 同音字替换（自定义 mapping）
    3. 编辑距离匹配热词（替换小距离候选）
    """

    # 常见同音字 / 术语误识别 mapping
    DEFAULT_HOMOPHONE_MAP: Dict[str, str] = {
        "支付宝": "支付宝",
        "微信": "微信",
        "阿里": "阿里",
        "智能体": "智能体",
        "代理": "代理",
        "知识库": "知识库",
        "图谱": "图谱",
        "数据库": "数据库",
    }

    def __init__(self, hotwords: Optional[List[str]] = None, homophone_map: Optional[Dict[str, str]] = None):
        self.hotwords = list(hotwords or [])
        self.homophone_map = dict(self.DEFAULT_HOMOPHONE_MAP)
        if homophone_map:
            self.homophone_map.update(homophone_map)

    def correct(self, text: str, hit_out: Optional[List[str]] = None) -> str:
        if not text:
            return text
        out = text

        # 1. 同音字 / 术语替换
        for wrong, right in self.homophone_map.items():
            if wrong != right and wrong in out:
                out = out.replace(wrong, right)

        # 2. 热词纠错：编辑距离 1 的同长度词替换
        if self.hotwords and hit_out is not None:
            words = re.split(r"(\s+)", out)
            for i, w in enumerate(words):
                if not w or w.isspace():
                    continue
                best = self._closest_hotword(w)
                if best and best != w:
                    hit_out.append(best)
                    words[i] = best
            out = "".join(words)

        # 3. 数字规范化（"一" 与 "1"）
        out = self._normalize_numbers(out)
        return out

    def _closest_hotword(self, word: str) -> Optional[str]:
        if not self.hotwords or len(word) < 2:
            return None
        best = None
        best_dist = 999
        for hw in self.hotwords:
            if abs(len(hw) - len(word)) > 1:
                continue
            d = _edit_distance(word, hw)
            if d < best_dist:
                best_dist = d
                best = hw
        if best_dist == 1 and best is not None:
            return best
        return None

    @staticmethod
    def _normalize_numbers(text: str) -> str:
        # 仅做最常见的中文数字 -> 阿拉伯数字（0-10），避免误伤
        mapping = {
            "零": "0", "一": "1", "二": "2", "三": "3", "四": "4",
            "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10",
        }
        out = []
        for ch in text:
            out.append(mapping.get(ch, ch))
        return "".join(out)


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(
                cur[-1] + 1,           # insert
                prev[j] + 1,           # delete
                prev[j - 1] + (ca != cb)  # substitute
            ))
        prev = cur
    return prev[-1]


class ConfidenceGate:
    """
    置信度兜底：
    - 低于阈值时保留主候选 + 兜底标记，供上层决定是否需要人工确认。
    - 文本长度异常（<=1 字符没有任何语义）也标记 fallback。
    """

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold

    def check(self, result: TranscriptionResult) -> TranscriptionResult:
        if not result.text or len(result.text.strip()) <= 1:
            result.fallback_used = True
            result.error = (result.error or "") + "; empty text"
            return result
        if result.confidence < self.threshold and result.candidates:
            # 置信度低：保留多候选（这里只有 1 个候选），并标记 fallback
            result.fallback_used = True
        return result


# ============================================================
# 主流水线
# ============================================================

class AudioPipeline:
    """
    语音输入管线（四步）：
    1) preprocess：解码 / 降噪 / AGC / VAD 切分
    2) asr：调引擎逐段转录
    3) postprocess：纠错 / 拼接
    4) confidence_gate：低置信度兜底
    """

    def __init__(self, config: Optional[AudioPipelineConfig] = None):
        self.config = config or AudioPipelineConfig()
        self.preprocessor = AudioPreprocessor()
        self.corrector = HotwordCorrector(self.config.hotwords)
        self.gate = ConfidenceGate(self.config.confidence_threshold)
        self._engines: Dict[str, ASREngine] = {}
        self._semantic_corrector = None
        self._init_engines()
        self._init_semantic_corrector()

    def _init_engines(self):
        cfg = self.config
        # Whisper 本地
        if cfg.default_provider == "whisper_local":
            try:
                self._engines["whisper_local"] = WhisperLocalEngine(cfg.whisper_model)
            except Exception as e:
                logger.warning(f"init whisper failed: {e}")
        # 阿里云
        if cfg.aliyun_appkey and cfg.aliyun_token:
            self._engines["aliyun"] = AliyunEngine(cfg.aliyun_appkey, cfg.aliyun_token)
        # 讯飞
        if cfg.iflytek_app_id and cfg.iflytek_api_key and cfg.iflytek_api_secret:
            self._engines["iflytek"] = IflytekEngine(
                cfg.iflytek_app_id, cfg.iflytek_api_key, cfg.iflytek_api_secret
            )
        # 兜底
        self._engines.setdefault("dummy", DummyEngine())

    def _init_semantic_corrector(self):
        """可选：初始化 LLM 语义纠错器（依赖 langchain + API key）。"""
        if not self.config.enable_semantic_correction:
            return
        try:
            from audio_semantic import make_default_llm_corrector
            self._semantic_corrector = make_default_llm_corrector()
            if self._semantic_corrector is not None:
                self._semantic_corrector.domain = self.config.domain_context
                logger.info("[AudioPipeline] LLM semantic corrector enabled")
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[AudioPipeline] semantic corrector init skipped: {e}")

    def _pick_engine(self, name: str) -> ASREngine:
        if name in self._engines and name != "dummy":
            return self._engines[name]
        # 依次降级
        for cand in ("whisper_local", "aliyun", "iflytek"):
            if cand in self._engines:
                return self._engines[cand]
        return self._engines["dummy"]

    def transcribe_bytes(
        self,
        data: bytes,
        mime: str = "audio/wav",
        lang: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> TranscriptionResult:
        """从原始音频字节转录"""
        lang = lang or self.config.default_lang
        engine = self._pick_engine(provider or self.config.default_provider)

        # 1. 解码
        pcm, meta = self.preprocessor.decode_wav(data)
        if meta.sample_rate == 0:
            # 不是 WAV，按原始 PCM 假设 16k16bit 单声道
            meta.sample_rate = 16000
        if self.config.enable_preprocess and meta.sample_rate > 0:
            pcm = self.preprocessor.denoise_and_agc(pcm, meta.sample_rate)

        # 2. VAD 切分
        segments = self.preprocessor.vad_segments(
            pcm,
            meta.sample_rate,
            max_segment_seconds=self.config.max_segment_seconds,
        )

        # 3. 逐段 ASR
        text_parts: List[str] = []
        confidences: List[float] = []
        last_provider = engine.name
        fallback = False
        first_error: Optional[str] = None
        for seg_pcm, start_sec, end_sec in segments:
            r = engine.transcribe(seg_pcm, meta.sample_rate, lang, self.config.hotwords)
            if r.error and not first_error:
                first_error = r.error
            if r.fallback_used:
                fallback = True
                # 主引擎失败，尝试下一个
                alt = self._pick_next(engine.name)
                if alt is not None and alt.name != engine.name:
                    alt_r = alt.transcribe(seg_pcm, meta.sample_rate, lang, self.config.hotwords)
                    if not alt_r.error and alt_r.text:
                        r = alt_r
                        last_provider = alt.name
            if r.text:
                text_parts.append(r.text)
            if r.confidence:
                confidences.append(r.confidence)

        merged_text = "".join(text_parts).strip()
        confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # 4. 纠错
        hits: List[str] = []
        if self.config.enable_correction:
            merged_text = self.corrector.correct(merged_text, hit_out=hits)

        # 4.5 LLM 语义纠错（兜底 + 上下文改写）
        llm_corrected = False
        llm_corrector_used = False
        if (
            self._semantic_corrector is not None
            and merged_text
            and (confidence < self.config.confidence_threshold or not merged_text)
        ):
            try:
                corrected = self._semantic_corrector.correct(merged_text)
                if corrected and corrected != merged_text:
                    merged_text = corrected
                    llm_corrected = True
                llm_corrector_used = True
            except Exception as e:  # noqa: BLE001
                logger.debug(f"semantic correction failed: {e}")

        # 5. 上下文兜底（domain hint 注入到返回，供上层 LLM 使用）
        debug_meta = {
            "segments": len(segments),
            "sample_rate": meta.sample_rate,
            "size_bytes": meta.size_bytes,
            "first_error": first_error,
            "llm_corrected": llm_corrected,
            "llm_corrector_used": llm_corrector_used,
        }

        result = TranscriptionResult(
            text=merged_text,
            confidence=confidence,
            provider=last_provider,
            lang=lang,
            duration_sec=meta.duration_sec,
            candidates=[(merged_text, confidence)] if merged_text else [],
            hotwords_hit=hits,
            fallback_used=fallback,
            error=first_error,
            debug=debug_meta,
        )

        # 6. 置信度兜底
        if self.config.enable_confidence_gate:
            result = self.gate.check(result)
        return result

    def _pick_next(self, current: str) -> Optional[ASREngine]:
        order = ["whisper_local", "aliyun", "iflytek"]
        for name in order:
            if name == current:
                continue
            if name in self._engines:
                # 仅在准备就绪时启用
                eng = self._engines[name]
                if hasattr(eng, "_is_ready") and not eng._is_ready():
                    continue
                return eng
        return None

    def transcribe(self, attachment) -> TranscriptionResult:
        """
        兼容 multimodal.py 中 _default_audio_transcriber 的位置。
        parameter: multimodal.Attachment
        """
        from multimodal import Modality  # 局部导入避免循环

        if attachment.modality != Modality.AUDIO:
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider="none",
                lang=self.config.default_lang,
                error=f"not audio: {attachment.modality}",
            )

        # 优先用已转录的缓存
        if attachment.text_content:
            return TranscriptionResult(
                text=attachment.text_content,
                confidence=0.99,
                provider="cache",
                lang=self.config.default_lang,
                cached=True,  # type: ignore[arg-type]
            )

        data = attachment.data
        if data is None and attachment.url:
            data = _download(attachment.url)
        if not data:
            return TranscriptionResult(
                text="",
                confidence=0.0,
                provider="none",
                lang=self.config.default_lang,
                error="no audio data",
            )

        result = self.transcribe_bytes(data, mime=attachment.mime or "audio/wav")
        # 写回缓存，便于后续复用
        attachment.text_content = result.text
        attachment.metadata = dict(attachment.metadata or {})
        attachment.metadata.update({
            "asr_provider": result.provider,
            "asr_confidence": result.confidence,
            "asr_lang": result.lang,
            "asr_fallback": result.fallback_used,
            "asr_hotwords": result.hotwords_hit,
            "asr_llm_corrected": result.debug.get("llm_corrected", False),
            "asr_domain_context": self.config.domain_context,
        })
        return result


def _download(url: str) -> Optional[bytes]:
    try:
        import httpx  # type: ignore
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url)
            if r.status_code == 200:
                return r.content
    except Exception as e:  # noqa: BLE001
        logger.warning(f"download audio failed: {e}")
    return None


# ============================================================
# 全局单例 + 兼容接口
# ============================================================

_pipeline: Optional[AudioPipeline] = None


def get_audio_pipeline() -> AudioPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = AudioPipeline()
    return _pipeline


def reset_audio_pipeline() -> None:
    global _pipeline
    _pipeline = None


def transcribe_audio(attachment) -> Tuple[str, Dict[str, Any]]:
    """
    供 multimodal.py / 上层直接调用。
    返回 (text, meta_dict)。
    """
    result = get_audio_pipeline().transcribe(attachment)
    return result.text, {
        "provider": result.provider,
        "confidence": result.confidence,
        "lang": result.lang,
        "duration_sec": result.duration_sec,
        "fallback_used": result.fallback_used,
        "hotwords_hit": result.hotwords_hit,
        "error": result.error,
    }


def _default_audio_transcriber(attachment) -> str:
    """multimodal.py 中的插入点：返回纯文本。"""
    return transcribe_audio(attachment)[0]
