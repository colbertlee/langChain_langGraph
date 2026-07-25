"""
多模态输入（Multimodal）

提供：
- Modality 枚举（TEXT / IMAGE / AUDIO / VIDEO / FILE / BINARY）
- Attachment 单个附件（type / data / mime / metadata / sha256）
- AttachmentStore 存储 + 检索（按 id / mime / 来源）
- image_caption / audio_transcribe / ocr_extract 简单处理函数
- 与 Message / Worker 接入：让 Message 可以携带附件

使用：
    store = get_attachment_store()
    att = store.add_from_file("image.png")
    msg = Message(
        msg_type=MessageType.TEXT,
        sender_id="user",
        receiver_id="vision_worker",
        content="图片里有什么？",
        attachments=[att],
    )
"""

import base64
import hashlib
import time
import uuid
import os
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


# ============================================================
# Modality / Attachment
# ============================================================

class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    FILE = "file"             # 通用文件
    BINARY = "binary"         # 任意二进制
    STRUCTURED = "structured" # JSON / dict


# MIME 推断
MIME_BY_MODALITY = {
    Modality.IMAGE: ["image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp"],
    Modality.AUDIO: ["audio/mpeg", "audio/wav", "audio/ogg", "audio/mp4", "audio/flac"],
    Modality.VIDEO: ["video/mp4", "video/webm", "video/avi", "video/quicktime"],
    Modality.FILE: ["application/octet-stream"],
    Modality.TEXT: ["text/plain", "text/markdown", "text/html", "text/csv"],
    Modality.STRUCTURED: ["application/json"],
}


def detect_modality_from_mime(mime: str) -> Modality:
    """根据 MIME 推断 modality"""
    if not mime:
        return Modality.FILE
    mime = mime.lower()
    if mime.startswith("image/"):
        return Modality.IMAGE
    if mime.startswith("audio/"):
        return Modality.AUDIO
    if mime.startswith("video/"):
        return Modality.VIDEO
    if mime.startswith("text/"):
        return Modality.TEXT
    if "json" in mime:
        return Modality.STRUCTURED
    return Modality.FILE


@dataclass
class Attachment:
    """一个附件"""
    attachment_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    modality: Modality = Modality.FILE
    mime: str = "application/octet-stream"
    filename: str = ""
    size_bytes: int = 0
    sha256: str = ""
    data: Optional[bytes] = None
    url: Optional[str] = None  # 如果 data 不在本地，给 URL
    caption: Optional[str] = None  # 自动生成的描述
    text_content: Optional[str] = None  # 文本提取（如 OCR / 转录）
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    source: str = "user"

    def is_inline(self) -> bool:
        """是否数据内联（可直接发送给 LLM）"""
        return self.data is not None

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["modality"] = self.modality.value
        # 不包含 data 字段（太大），只 metadata
        d.pop("data", None)
        return d

    def to_b64(self) -> Optional[str]:
        """转 base64（用于传输）"""
        if self.data is None:
            return None
        return base64.b64encode(self.data).decode("ascii")

    @classmethod
    def from_dict(cls, d: Dict) -> "Attachment":
        d = dict(d)
        if "modality" in d and isinstance(d["modality"], str):
            d["modality"] = Modality(d["modality"])
        return cls(**d)

    @classmethod
    def from_file(cls, path: str, source: str = "user", metadata: Optional[Dict] = None) -> "Attachment":
        """从文件创建附件"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        with open(path, "rb") as f:
            data = f.read()
        mime = _guess_mime_from_filename(path)
        mod = detect_modality_from_mime(mime)
        sha = hashlib.sha256(data).hexdigest()
        return cls(
            modality=mod,
            mime=mime,
            filename=os.path.basename(path),
            size_bytes=len(data),
            sha256=sha,
            data=data,
            source=source,
            metadata=metadata or {},
        )


def _guess_mime_from_filename(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    mapping = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".csv": "text/csv",
        ".html": "text/html",
    }
    return mapping.get(ext, "application/octet-stream")


# ============================================================
# AttachmentStore
# ============================================================

class AttachmentStore:
    """
    附件存储

    - 按 attachment_id 存储
    - 按 mime / modality / source 检索
    - 计算 sha256 去重
    """

    def __init__(self, max_total_bytes: int = 100 * 1024 * 1024):
        self._items: Dict[str, Attachment] = {}
        self._max_total = max_total_bytes
        self._total_size = 0
        self._lock = False  # 简单 bool，因为单线程使用

    def add(self, att: Attachment) -> Attachment:
        # 检查重复
        if att.sha256:
            for existing in self._items.values():
                if existing.sha256 == att.sha256:
                    logger.debug(f"Attachment duplicate: {att.sha256[:8]}")
                    return existing

        # 容量检查
        if self._total_size + att.size_bytes > self._max_total:
            raise MemoryError(
                f"Attachment store full: {self._total_size + att.size_bytes} > {self._max_total}"
            )
        self._items[att.attachment_id] = att
        self._total_size += att.size_bytes
        logger.info(
            f"[AttachmentStore] Added {att.attachment_id[:8]} "
            f"modality={att.modality.value} mime={att.mime} size={att.size_bytes}"
        )
        return att

    def add_from_file(
        self,
        path: str,
        source: str = "user",
        metadata: Optional[Dict] = None,
    ) -> Attachment:
        return self.add(Attachment.from_file(path, source=source, metadata=metadata))

    def get(self, attachment_id: str) -> Optional[Attachment]:
        return self._items.get(attachment_id)

    def delete(self, attachment_id: str) -> bool:
        att = self._items.pop(attachment_id, None)
        if att is None:
            return False
        self._total_size -= att.size_bytes
        return True

    def query(
        self,
        modality: Optional[Modality] = None,
        mime_prefix: Optional[str] = None,
        source: Optional[str] = None,
        limit: int = 100,
    ) -> List[Attachment]:
        out = list(self._items.values())
        if modality:
            out = [a for a in out if a.modality == modality]
        if mime_prefix:
            out = [a for a in out if a.mime.startswith(mime_prefix)]
        if source:
            out = [a for a in out if a.source == source]
        return out[-limit:]

    def stats(self) -> Dict[str, Any]:
        by_modality: Dict[str, int] = {}
        for a in self._items.values():
            by_modality[a.modality.value] = by_modality.get(a.modality.value, 0) + 1
        return {
            "count": len(self._items),
            "total_bytes": self._total_size,
            "max_bytes": self._max_total,
            "by_modality": by_modality,
        }


# ============================================================
# 简单处理器（可被真实 LLM 替换）
# ============================================================

class AttachmentProcessor:
    """
    简单附件处理器。

    内置：
    - 文本提取（如 .txt 直接读）
    - OCR（占位，需接入真实 OCR 引擎）
    - 转录（占位，需接入 Whisper）
    - 图像 caption（占位）

    使用：
        proc = AttachmentProcessor()
        text = await proc.process(att)  # 返回提取出的文本
    """

    def __init__(
        self,
        text_extractors: Optional[Dict[str, Callable[[Attachment], str]]] = None,
        image_captioner: Optional[Callable[[Attachment], str]] = None,
        audio_transcriber: Optional[Callable[[Attachment], str]] = None,
    ):
        self.text_extractors = text_extractors or {}
        self.image_captioner = image_captioner or _default_image_captioner
        self.audio_transcriber = audio_transcriber or _default_audio_transcriber

    async def process(self, att: Attachment) -> str:
        """处理附件，返回文本"""
        if att.modality == Modality.TEXT:
            if att.text_content:
                return att.text_content
            if att.data:
                try:
                    return att.data.decode("utf-8", errors="replace")
                except Exception as e:
                    logger.warning(f"text decode error: {e}")
                    return ""

        if att.modality == Modality.STRUCTURED:
            if att.data:
                try:
                    import json
                    obj = json.loads(att.data.decode("utf-8"))
                    return json.dumps(obj, ensure_ascii=False, indent=2)
                except Exception:
                    pass

        if att.modality == Modality.IMAGE:
            caption = self.image_captioner(att)
            att.caption = caption
            return caption

        if att.modality == Modality.AUDIO:
            # 兼容两种签名：transcriber(att) -> str | transcriber(att) -> (str, meta)
            ret = self.audio_transcriber(att)
            if isinstance(ret, tuple):
                text, meta = ret
                if isinstance(meta, dict):
                    att.metadata = dict(att.metadata or {})
                    att.metadata.update({k: v for k, v in meta.items() if v is not None})
            else:
                text = ret
            att.text_content = text
            return text

        if att.modality == Modality.FILE:
            return self.text_extractors.get(att.mime, _default_file_extractor)(att)

        return ""


def _default_image_captioner(att: Attachment) -> str:
    """占位：真实环境接入 vision LLM"""
    return f"[image:{att.filename}] (no captioner configured, size={att.size_bytes} bytes)"


def _default_audio_transcriber(att: Attachment) -> str:
    """
    默认音频转录器。
    委托给 audio_pipeline 中的实现（包含音频预处理 / Whisper 或阿里云 / 讯飞
    / 热词纠错 / 置信度兜底 / 上下文提示）。
    """
    try:
        from audio_pipeline import transcribe_audio  # 局部导入避免循环
        text, meta = transcribe_audio(att)
        if meta.get("error"):
            logger.debug(f"[audio] fallback: {meta['error']}")
        return text
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[audio] pipeline unavailable, use placeholder: {e}")
        return f"[audio:{att.filename}] (pipeline unavailable: {e})"


def _default_file_extractor(att: Attachment) -> str:
    return f"[file:{att.filename}] (no extractor configured, size={att.size_bytes} bytes)"


# ============================================================
# 全局单例
# ============================================================

_attachment_store: Optional[AttachmentStore] = None


def get_attachment_store() -> AttachmentStore:
    global _attachment_store
    if _attachment_store is None:
        _attachment_store = AttachmentStore()
    return _attachment_store


def reset_attachment_store() -> None:
    global _attachment_store
    _attachment_store = None