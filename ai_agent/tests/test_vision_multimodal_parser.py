"""v2.1 — vision_multimodal_parser 单元测试。"""
import base64
from pathlib import Path

import pytest


# ============================================================
# parse_attrs
# ============================================================
class TestParseAttrs:
    def test_basic(self):
        from vision_multimodal_parser import parse_attrs

        attrs = parse_attrs('filename="cat.png" mime="image/png" data_b64_len="123"')
        assert attrs["filename"] == "cat.png"
        assert attrs["mime"] == "image/png"
        assert attrs["data_b64_len"] == "123"

    def test_empty(self):
        from vision_multimodal_parser import parse_attrs

        assert parse_attrs("") == {}


# ============================================================
# parse_vision_message
# ============================================================
class TestParseVisionMessage:
    def test_no_vision_tag_returns_single_text(self):
        from vision_multimodal_parser import parse_vision_message

        blocks = parse_vision_message("hello world")
        assert blocks == [{"type": "text", "text": "hello world"}]

    def test_single_inline_image(self):
        from vision_multimodal_parser import parse_vision_message

        text = (
            'describe this\n\n<vision_attachments>\n'
            '<multimodal_image filename="cat.png" mime="image/png" data_b64="AAAA" />\n'
            '</vision_attachments>'
        )
        blocks = parse_vision_message(text)
        assert len(blocks) == 2
        # 第一个是 text block，strip 掉 vision 标签后的纯文本
        assert blocks[0]["type"] == "text"
        assert "describe this" in blocks[0]["text"]
        assert "<vision_attachments>" not in blocks[0]["text"]
        # 第二个是 image_url
        assert blocks[1]["type"] == "image_url"
        assert blocks[1]["image_url"]["url"] == "data:image/png;base64,AAAA"
        assert blocks[1]["filename"] == "cat.png"

    def test_multiple_images(self):
        from vision_multimodal_parser import parse_vision_message

        text = (
            '<vision_attachments>\n'
            '<multimodal_image filename="a.png" mime="image/png" data_b64="x" />\n'
            '<multimodal_image filename="b.jpg" mime="image/jpeg" data_b64="y" />\n'
            '</vision_attachments>'
        )
        blocks = parse_vision_message(text)
        imgs = [b for b in blocks if b["type"] == "image_url"]
        assert len(imgs) == 2
        assert imgs[0]["filename"] == "a.png"
        assert imgs[1]["image_url"]["url"] == "data:image/jpeg;base64,y"

    def test_fallback_to_file_id(self, tmp_path):
        """data_b64 缺失时按 file_id 从 upload_root 读图。"""
        from vision_multimodal_parser import parse_vision_message

        # 写一个假 png 到 upload_root
        file_id = "fid-xyz"
        (tmp_path / f"{file_id}_cat.png").write_bytes(b"\x89PNG fake")
        text = (
            f'<vision_attachments>\n'
            f'<multimodal_image filename="cat.png" mime="image/png" file_id="{file_id}" />\n'
            f'</vision_attachments>'
        )
        blocks = parse_vision_message(text, upload_root=tmp_path)
        imgs = [b for b in blocks if b["type"] == "image_url"]
        assert len(imgs) == 1
        # data URL 含 base64
        url = imgs[0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        # 解码回原字节
        b64 = url.split(",", 1)[1]
        assert base64.b64decode(b64) == b"\x89PNG fake"

    def test_missing_data_and_file_id_skipped(self, tmp_path):
        """既无 data_b64 也无 file_id → 跳过该 image。"""
        from vision_multimodal_parser import parse_vision_message

        text = (
            '<vision_attachments>\n'
            '<multimodal_image filename="orphan.png" mime="image/png" />\n'
            '</vision_attachments>'
        )
        blocks = parse_vision_message(text, upload_root=tmp_path)
        # 只有 text block（cleaned 后为空字符串也会保留吗？看实现）
        imgs = [b for b in blocks if b["type"] == "image_url"]
        assert len(imgs) == 0


# ============================================================
# build_multimodal_human_message
# ============================================================
class TestBuildMultimodalHumanMessage:
    def test_no_vision_returns_text_human_message(self):
        from vision_multimodal_parser import build_multimodal_human_message

        msg = build_multimodal_human_message("plain text")
        # HumanMessage.content 是 string（与 LangChain 旧行为兼容）
        assert msg.content == "plain text"

    def test_with_vision_returns_multimodal_human_message(self):
        from vision_multimodal_parser import build_multimodal_human_message

        text = (
            'look at this\n\n<vision_attachments>\n'
            '<multimodal_image filename="x.png" mime="image/png" data_b64="AB" />\n'
            '</vision_attachments>'
        )
        msg = build_multimodal_human_message(text)
        # HumanMessage.content 是 list[dict]
        assert isinstance(msg.content, list)
        assert len(msg.content) == 2
        assert msg.content[0]["type"] == "text"
        assert msg.content[1]["type"] == "image_url"

    def test_only_image_no_text(self):
        """只有 vision 标签没有任何文本 → content 仅含 image_url。"""
        from vision_multimodal_parser import build_multimodal_human_message

        text = (
            '<vision_attachments>\n'
            '<multimodal_image filename="a.png" mime="image/png" data_b64="X" />\n'
            '</vision_attachments>'
        )
        msg = build_multimodal_human_message(text)
        assert isinstance(msg.content, list)
        assert len(msg.content) == 1
        assert msg.content[0]["type"] == "image_url"


# ============================================================
# 端到端：AIAgent._build_messages_payload 用 multimodal blocks
# ============================================================
class TestAIAgentMultimodalInjection:
    def _stub_agent(self):
        from agent import AIAgent

        agent = AIAgent.__new__(AIAgent)
        agent.tools = []
        agent._initial_tools = []
        agent._extra_tools = []
        agent._session_tool_map = {}
        agent.current_session_id = "sm"
        # memory / context stub
        agent.memory_store = type("M", (), {"get_context": staticmethod(lambda *a, **k: "")})()
        agent.context_manager = type(
            "C",
            (),
            {"build_context": staticmethod(lambda *a, **k: "")},
        )()
        agent._pending_vision_blocks = []
        return agent

    def test_plain_text_when_no_blocks(self):
        agent = self._stub_agent()
        msgs = agent._build_messages_payload("hi", "hi")
        # 第二条 HumanMessage.content 是 string
        from langchain_core.messages import HumanMessage

        hum = [m for m in msgs if isinstance(m, HumanMessage)][0]
        assert hum.content == "hi"
        assert isinstance(hum.content, str)

    def test_multimodal_when_blocks_set(self):
        agent = self._stub_agent()
        agent.set_pending_vision_blocks([
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZZ"}},
        ])
        msgs = agent._build_messages_payload("describe", "describe")
        from langchain_core.messages import HumanMessage

        hum = [m for m in msgs if isinstance(m, HumanMessage)][0]
        assert isinstance(hum.content, list)
        # 第一个 text block 应是 user 文本
        assert hum.content[0]["type"] == "text"
        assert "describe" in hum.content[0]["text"]
        # 第二个是 image_url
        assert hum.content[1]["type"] == "image_url"
        assert hum.content[1]["image_url"]["url"] == "data:image/png;base64,ZZ"
        # 用完即清空
        assert agent._pending_vision_blocks == []

    def test_clear_pending_after_build(self):
        agent = self._stub_agent()
        agent.set_pending_vision_blocks([{"type": "image_url", "image_url": {"url": "x"}}])
        agent._build_messages_payload("a", "a")
        # 第二次 build 应该不残留（虽然只有 image_url 没 text，会 fallback 用上一轮的 final_input）
        # 但 pending 已清空 → 第二次 build 应该用纯文本
        msgs2 = agent._build_messages_payload("b", "b")
        from langchain_core.messages import HumanMessage

        hum = [m for m in msgs2 if isinstance(m, HumanMessage)][0]
        assert hum.content == "b"  # string because pending cleared
