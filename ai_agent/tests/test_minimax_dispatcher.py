"""
MiniMax MCP dispatcher & 路径自创建 单测

验证:
- _call_external_mcp 在 HITL 拦截时返回 pending_approval 状态
- _ensure_output_paths 会自动创建 MINIMAX_MCP_BASE_PATH / DATABASE_PATH
- _build_minimax_tools 生成的 langchain tool 数量与名称正确
- permission.is_require_approval 默认对 minimax 高危工具返回 True
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_external import _ensure_output_paths
from permission import (
    is_require_approval,
    add_require_approval_tool,
    remove_require_approval_tool,
    require_approval_tools,
    DEFAULT_REQUIRE_APPROVAL_TOOLS,
)
import tools as _tools_mod


class TestEnsureOutputPaths(unittest.TestCase):
    def test_creates_minimax_base_path(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {
                "env": {
                    "MINIMAX_API_KEY": "sk-x",
                    "MINIMAX_MCP_BASE_PATH": os.path.join(d, "minimax"),
                    "MINIMAX_API_HOST": "https://api.minimax.chat",
                    "MINIMAX_API_RESOURCE_MODE": "url",
                }
            }
            created = _ensure_output_paths(cfg)
            self.assertTrue(any(c.endswith("minimax") for c in created))
            self.assertTrue(os.path.isdir(os.path.join(d, "minimax")))

    def test_creates_database_path_parent(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = {"env": {"DATABASE_PATH": os.path.join(d, "sub", "data.db")}}
            created = _ensure_output_paths(cfg)
            self.assertTrue(os.path.isdir(os.path.join(d, "sub")))
            self.assertTrue(any("sub" in c for c in created))

    def test_skips_unresolved_placeholder(self):
        # ${X} 未填时,不创建任何目录
        cfg = {"env": {"MINIMAX_MCP_BASE_PATH": "${MINIMAX_MCP_BASE_PATH}"}}
        created = _ensure_output_paths(cfg)
        self.assertEqual(created, [])


class TestHitlDefaults(unittest.TestCase):
    def setUp(self):
        # 重置 _REQUIRE_APPROVAL_TOOLS 后重新加载默认
        from permission import _REQUIRE_APPROVAL_TOOLS
        _REQUIRE_APPROVAL_TOOLS.clear()
        _REQUIRE_APPROVAL_TOOLS.update(DEFAULT_REQUIRE_APPROVAL_TOOLS)

    def test_minimax_high_risk_tools_require_approval(self):
        self.assertTrue(is_require_approval("minimax_voice_clone"))
        self.assertTrue(is_require_approval("minimax_generate_video"))
        self.assertTrue(is_require_approval("minimax_text_to_image"))
        self.assertTrue(is_require_approval("minimax_play_audio"))

    def test_readonly_tools_do_not_require_approval(self):
        self.assertFalse(is_require_approval("minimax_list_voices"))
        self.assertFalse(is_require_approval("minimax_query_video_generation"))

    def test_add_remove(self):
        add_require_approval_tool("minimax_list_voices")
        self.assertTrue(is_require_approval("minimax_list_voices"))
        remove_require_approval_tool("minimax_list_voices")
        self.assertFalse(is_require_approval("minimax_list_voices"))


class TestMinimaxDispatcherHitlBlock(unittest.TestCase):
    """验证 dispatcher 在 HITL 拦截下的行为"""

    def setUp(self):
        from permission import _REQUIRE_APPROVAL_TOOLS
        _REQUIRE_APPROVAL_TOOLS.clear()
        _REQUIRE_APPROVAL_TOOLS.update(DEFAULT_REQUIRE_APPROVAL_TOOLS)

    def test_dispatcher_returns_pending_approval(self):
        # 不启动任何真实 MCP,直接验证拦截
        result = _tools_mod.call_external_mcp("minimax", "text_to_image", {"prompt": "cat"})
        # 应该是 JSON 字符串,status=pending_approval
        data = json.loads(result)
        self.assertEqual(data["status"], "pending_approval")
        self.assertEqual(data["tool"], "minimax_text_to_image")

    def test_dispatcher_pass_through_after_remove(self):
        # 把拦截摘掉,dispatcher 会尝试真正调用 MCP(此时未启,会得到 server-not-running 的回执,
        # 但不再是 pending_approval)
        remove_require_approval_tool("minimax_text_to_image")
        result = _tools_mod.call_external_mcp("minimax", "text_to_image", {"prompt": "cat"})
        # 不应再是 pending_approval
        try:
            data = json.loads(result)
            self.assertNotEqual(data.get("status"), "pending_approval")
        except json.JSONDecodeError:
            # 非 JSON 字符串也可以,只要不含 pending_approval
            self.assertNotIn("pending_approval", result)


class TestBuildMinimaxTools(unittest.TestCase):
    def test_builds_expected_tools(self):
        ts = _tools_mod.build_minimax_tools()
        names = {t.name for t in ts}
        expected = {
            "minimax_text_to_audio",
            "minimax_list_voices",
            "minimax_voice_clone",
            "minimax_voice_design",
            "minimax_play_audio",
            "minimax_music_generation",
            "minimax_generate_video",
            "minimax_image_to_video",
            "minimax_query_video_generation",
            "minimax_text_to_image",
        }
        self.assertSetEqual(names, expected)

    def test_tools_have_descriptions(self):
        ts = _tools_mod.build_minimax_tools()
        for t in ts:
            self.assertTrue(t.description, "tool {} missing description".format(t.name))
            self.assertIn("minimax", t.description.lower())

    def test_get_all_tools_includes_minimax(self):
        all_tools = _tools_mod.get_all_tools()
        names = {t.name for t in all_tools}
        self.assertIn("minimax_text_to_audio", names)
        self.assertIn("minimax_text_to_image", names)


if __name__ == "__main__":
    unittest.main()