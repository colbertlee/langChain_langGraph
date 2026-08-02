"""
minimax MCP 配置 & 管理器 单测

不依赖真实 stdio 子进程 —— 用 tmp 目录构造 mcp_config.json 与 fake external command,
验证:
  - mcp_config.json 里 minimax 条目字段齐全(required_env / env_defaults)
  - _materialize_env / _env_value_is_missing 正确解析 ${VAR}
  - ExternalMCPManager._check_required_env 能列出缺失项
  - _save_config 原子写不破坏原文件
"""
import json
import os
import sys
import unittest

# 让 tests/ 能直接 import ai_agent 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_external import (
    ExternalMCPManager,
    _materialize_env,
    _env_value_is_missing,
)


CONFIG_TPL = {
    "external_servers": {
        "minimax": {
            "enabled": False,
            "command": "npx",
            "args": ["-y", "minimax-mcp-js"],
            "env": {
                "MINIMAX_API_KEY": "${MINIMAX_API_KEY}",
                "MINIMAX_MCP_BASE_PATH": "${MINIMAX_MCP_BASE_PATH}",
                "MINIMAX_API_HOST": "${MINIMAX_API_HOST}",
                "MINIMAX_API_RESOURCE_MODE": "${MINIMAX_API_RESOURCE_MODE}",
            },
            "description": "MiniMax 官方 MCP",
            "required_env": [
                "MINIMAX_API_KEY",
                "MINIMAX_MCP_BASE_PATH",
                "MINIMAX_API_HOST",
            ],
            "env_defaults": {
                "MINIMAX_API_HOST": "https://api.minimax.chat",
                "MINIMAX_API_RESOURCE_MODE": "url",
            },
        }
    }
}


def _write_config(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


class TestMaterializeEnv(unittest.TestCase):
    def test_resolves_known_var(self):
        os.environ["FOO_BAR_TEST"] = "hello"
        self.assertEqual(_materialize_env({"X": "${FOO_BAR_TEST}"})["X"], "hello")

    def test_keeps_placeholder_when_missing(self):
        os.environ.pop("__MINIMAX_NONEXIST__", None)
        v = _materialize_env({"X": "${__MINIMAX_NONEXIST__}"})["X"]
        self.assertEqual(v, "${__MINIMAX_NONEXIST__}")

    def test_missing_detection(self):
        self.assertTrue(_env_value_is_missing(""))
        self.assertTrue(_env_value_is_missing("${X}"))
        self.assertFalse(_env_value_is_missing("https://api.minimax.chat"))


class TestMinimaxConfigShape(unittest.TestCase):
    def test_minimax_entry_has_required_fields(self):
        cfg = CONFIG_TPL["external_servers"]["minimax"]
        self.assertIn("required_env", cfg)
        self.assertIn("env_defaults", cfg)
        for k in ("MINIMAX_API_KEY", "MINIMAX_MCP_BASE_PATH", "MINIMAX_API_HOST"):
            self.assertIn(k, cfg["required_env"])
        self.assertEqual(
            cfg["env_defaults"]["MINIMAX_API_HOST"],
            "https://api.minimax.chat",
        )


class TestCheckRequiredEnv(unittest.TestCase):
    def setUp(self):
        # 清理可能干扰的环境变量
        for k in ("MINIMAX_API_KEY", "MINIMAX_MCP_BASE_PATH", "MINIMAX_API_HOST"):
            os.environ.pop(k, None)

    def test_all_missing(self):
        mgr = ExternalMCPManager.__new__(ExternalMCPManager)
        cfg = CONFIG_TPL["external_servers"]["minimax"]
        missing = mgr._check_required_env(cfg)
        self.assertSetEqual(
            set(missing),
            {"MINIMAX_API_KEY", "MINIMAX_MCP_BASE_PATH", "MINIMAX_API_HOST"},
        )

    def test_partial_missing(self):
        os.environ["MINIMAX_API_KEY"] = "sk-test"
        mgr = ExternalMCPManager.__new__(ExternalMCPManager)
        cfg = CONFIG_TPL["external_servers"]["minimax"]
        missing = mgr._check_required_env(cfg)
        self.assertSetEqual(
            set(missing),
            {"MINIMAX_MCP_BASE_PATH", "MINIMAX_API_HOST"},
        )

    def test_all_configured(self):
        os.environ["MINIMAX_API_KEY"] = "sk-test"
        os.environ["MINIMAX_MCP_BASE_PATH"] = "./output/minimax"
        os.environ["MINIMAX_API_HOST"] = "https://api.minimax.chat"
        mgr = ExternalMCPManager.__new__(ExternalMCPManager)
        cfg = CONFIG_TPL["external_servers"]["minimax"]
        missing = mgr._check_required_env(cfg)
        self.assertEqual(missing, [])


class TestSaveConfigAtomic(unittest.TestCase):
    def test_save_replaces_and_no_leftover(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            cfg_path = os.path.join(d, "mcp_config.json")
            _write_config(cfg_path, CONFIG_TPL)
            mgr = ExternalMCPManager.__new__(ExternalMCPManager)
            mgr.config_path = cfg_path

            payload = json.loads(open(cfg_path, "r", encoding="utf-8").read())
            payload["external_servers"]["minimax"]["enabled"] = True
            mgr._save_config(payload)

            # 原文件应被原子覆盖,内容包含 enabled=True
            after = json.loads(open(cfg_path, "r", encoding="utf-8").read())
            self.assertTrue(after["external_servers"]["minimax"]["enabled"])
            # 不应残留临时文件
            leftovers = [n for n in os.listdir(d) if n.startswith(".mcp_config.")]
            self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()