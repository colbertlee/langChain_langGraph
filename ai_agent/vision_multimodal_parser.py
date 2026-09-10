"""v2.1 — Vision Multimodal Message Parser

负责：
  1) parse_attrs：解析 ``<multimodal_image filename="x.png" mime="image/png" data_b64="..." />``
     的属性串为 dict
  2) parse_vision_message：从含 <vision_attachments> 标签的文本里抽出 image_url blocks
  3) build_multimodal_human_message：把含 vision 标签的文本转成
     HumanMessage(content=[{type:text}, {type:image_url, ...}])

设计：
  - 强依赖 file_parser.build_image_multimodal_block
  - 当 data_b64 缺失但有 file_id 时，按 upload_root 找文件并读 base64
  - 解析失败时降级为纯文本 HumanMessage
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# parse_attrs
# ============================================================

_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def parse_attrs(s: str) -> Dict[str, str]:
    """把 ``<tag key1="v1" key2="v2" />`` 的属性串解析为 dict。"""
    if not s:
        return {}
    return {m.group(1): m.group(2) for m in _ATTR_RE.finditer(s)}


# ============================================================
# 内部：清理文本中的 <vision_attachments> 标签
# ============================================================

_VISION_OPEN_RE = re.compile(r"<vision_attachments[^>]*>", re.IGNORECASE)
_VISION_CLOSE_RE = re.compile(r"</vision_attachments[^>]*>", re.IGNORECASE)
_MULTI_IMG_RE = re.compile(
    r"<multimodal_image\b([^>]*?)/?>", re.IGNORECASE
)


def _clean_text(text: str) -> str:
    """把 <vision_attachments>...</vision_attachments> 段从文本里剥掉。"""
    if not text:
        return ""
    # 先整段去掉
    out = _VISION_OPEN_RE.sub("", text)
    out = _VISION_CLOSE_RE.sub("", out)
    # 再去掉单独的 multimodal_image
    out = _MULTI_IMG_RE.sub("", out)
    return out.strip()


def _find_image_matches(text: str) -> List[re.Match]:
    return list(_MULTI_IMG_RE.finditer(text or ""))


def _file_path_from_id(file_id: str, upload_root: Optional[Path]) -> Optional[Path]:
    """根据 file_id 在 upload_root 下找文件（允许带或带不带后缀）。"""
    if not file_id or upload_root is None:
        return None
    root = Path(upload_root)
    if not root.exists():
        return None
    # 1) 精确匹配
    for ext in ("", ".png", ".jpg", ".jpeg", ".gif", ".webp"):
        p = root / f"{file_id}{ext}"
        if p.exists() and p.is_file():
            return p
    # 2) 前缀匹配
    candidates = list(root.glob(f"{file_id}*"))
    for p in candidates:
        if p.is_file():
            return p
    return None


# ============================================================
# parse_vision_message
# ============================================================


def parse_vision_message(
    text: str, upload_root: Optional[Path] = None
) -> List[Dict[str, Any]]:
    """把含 vision 标签的文本解析为 block 列表。

    返回形如：
      [
        {"type": "text", "text": "..."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}, "filename": "..."},
        ...
      ]

    行为：
      - 若没 <vision_attachments> 段 → 返回单一 text block
      - 解析 multimodal_image 的 data_b64：优先用属性里的；否则按 file_id 读 upload_root
      - data / file_id 都缺 → 跳过该图
    """
    if not text:
        return []
    if "<vision_attachments" not in text:
        return [{"type": "text", "text": text}]

    blocks: List[Dict[str, Any]] = []
    text_cleaned = _clean_text(text)
    if text_cleaned:
        blocks.append({"type": "text", "text": text_cleaned})

    for m in _find_image_matches(text):
        attrs = parse_attrs(m.group(1))
        fname = attrs.get("filename", "image")
        mime = attrs.get("mime", "image/png")
        data_b64 = attrs.get("data_b64", "") or ""
        file_id = attrs.get("file_id", "") or ""
        # 1) 直接用 data_b64
        if data_b64:
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data_b64}"},
                "filename": fname,
            })
            continue
        # 2) file_id + upload_root
        if file_id and upload_root is not None:
            p = _file_path_from_id(file_id, upload_root)
            if p is not None and p.exists() and p.is_file():
                try:
                    raw = p.read_bytes()
                    b64 = base64.b64encode(raw).decode("ascii")
                    # 修正 mime
                    ext = p.suffix.lower().lstrip(".")
                    mime_map = {
                        "png": "image/png",
                        "jpg": "image/jpeg",
                        "jpeg": "image/jpeg",
                        "gif": "image/gif",
                        "webp": "image/webp",
                    }
                    final_mime = mime_map.get(ext, mime)
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{final_mime};base64,{b64}"},
                        "filename": fname,
                    })
                    continue
                except Exception:
                    pass
        # 3) 都没有 → 跳过
    return blocks


# ============================================================
# build_multimodal_human_message
# ============================================================


def build_multimodal_human_message(
    text: str, upload_root: Optional[Path] = None
):
    """把含 vision 标签的文本转成 HumanMessage。

    行为：
      - 无 vision 段 → HumanMessage(content=text)  // string
      - 有 vision 段 → HumanMessage(content=[text_block, image_url, ...])  // list
    """
    from langchain_core.messages import HumanMessage

    blocks = parse_vision_message(text, upload_root=upload_root)
    if not blocks:
        return HumanMessage(content="")
    # 若只有 1 个 text block 且没图 → 保持 content 为 string
    if len(blocks) == 1 and blocks[0].get("type") == "text":
        return HumanMessage(content=blocks[0]["text"])
    return HumanMessage(content=blocks)


__all__ = [
    "parse_attrs",
    "parse_vision_message",
    "build_multimodal_human_message",
]
