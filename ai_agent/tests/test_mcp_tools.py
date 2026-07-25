"""mcp_tools.py 单元测试。

覆盖：文件 / 网络 / 系统 / 数据 / 时间 工具 + register_all_mcp_tools。
"""
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from mcp_server import get_mcp_tool_registry, MCPToolRegistry
import mcp_tools


# ==================== Fixtures ====================

@pytest.fixture(autouse=True)
def reset_registry():
    """每个测试后清空注册表，避免污染。"""
    yield
    get_mcp_tool_registry()["tools"].clear()


# ==================== 文件系统工具 ====================

class TestFileTools:
    """测试 handle_read_file / handle_write_file / handle_list_directory"""

    def test_read_file_success(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        result = mcp_tools.handle_read_file({"path": str(f)})
        assert result == "hello world"

    def test_read_file_truncation(self, tmp_path):
        f = tmp_path / "big.txt"
        f.write_text("x" * 6000, encoding="utf-8")
        result = mcp_tools.handle_read_file({"path": str(f)})
        assert "... (truncated)" in result
        assert len(result) <= 5050

    def test_read_file_not_found(self):
        result = mcp_tools.handle_read_file({"path": "nonexistent.txt"})
        assert "File not found" in result

    def test_read_file_no_path(self):
        result = mcp_tools.handle_read_file({})
        assert "path is required" in result

    def test_read_file_path_traversal_denied(self):
        result = mcp_tools.handle_read_file({"path": "../etc/passwd"})
        assert "Access denied" in result

    def test_read_file_absolute_path_denied(self):
        result = mcp_tools.handle_read_file({"path": "/etc/passwd"})
        assert "Access denied" in result

    def test_write_file_success(self, tmp_path):
        f = tmp_path / "out.txt"
        result = mcp_tools.handle_write_file({"path": str(f), "content": "hi"})
        assert "Success" in result
        assert f.read_text(encoding="utf-8") == "hi"

    def test_write_file_no_path(self):
        result = mcp_tools.handle_write_file({"content": "hi"})
        assert "path is required" in result

    def test_write_file_path_traversal_denied(self):
        result = mcp_tools.handle_write_file({"path": "../bad.txt", "content": "x"})
        assert "Access denied" in result

    def test_write_file_io_error(self, tmp_path):
        # 用目录当文件路径
        result = mcp_tools.handle_write_file({"path": str(tmp_path), "content": "x"})
        assert "Error" in result

    def test_list_directory_success(self, tmp_path):
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        (tmp_path / "b").mkdir()
        result = mcp_tools.handle_list_directory({"path": str(tmp_path)})
        assert "[FILE] a.txt" in result
        assert "[DIR]  b" in result

    def test_list_directory_path_traversal_denied(self):
        result = mcp_tools.handle_list_directory({"path": "../"})
        assert "Access denied" in result

    def test_list_directory_not_found(self):
        result = mcp_tools.handle_list_directory({"path": "./nonexistent_dir_xyz"})
        assert "Error" in result


# ==================== 网络工具 ====================

class TestNetworkTools:
    """测试 handle_curl（mock requests.get / requests.post）。"""

    @patch("requests.get")
    def test_curl_get_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"Content-Type": "application/json"}
        mock_resp.text = '{"ok": true}'
        mock_get.return_value = mock_resp

        result = mcp_tools.handle_curl({"url": "https://example.com"})
        assert "Status: 200" in result
        assert "application/json" in result

    @patch("requests.post")
    def test_curl_post_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.headers = {}
        mock_resp.text = "created"
        mock_post.return_value = mock_resp

        result = mcp_tools.handle_curl({"url": "https://api.example.com", "method": "POST", "data": {"x": 1}})
        assert "Status: 201" in result
        mock_post.assert_called_once()

    def test_curl_no_url(self):
        result = mcp_tools.handle_curl({})
        assert "url is required" in result

    def test_curl_unsupported_method(self):
        result = mcp_tools.handle_curl({"url": "https://x.com", "method": "DELETE"})
        assert "Unsupported method" in result

    @patch("requests.get")
    def test_curl_request_exception(self, mock_get):
        import requests as real_requests
        mock_get.side_effect = real_requests.ConnectionError("network down")
        result = mcp_tools.handle_curl({"url": "https://x.com"})
        assert "Error" in result
        assert "network down" in result

    def test_whoami_returns_valid_json(self):
        result = mcp_tools.handle_whoami({})
        data = json.loads(result)
        assert "username" in data
        assert "hostname" in data
        assert "platform" in data
        assert "python_version" in data


# ==================== 开发工具 ====================

class TestDevTools:
    """测试 git / docker（mock subprocess.run）。"""
    # mcp_tools.py 在函数内 import subprocess，所以 mock "subprocess.run"（全局模块）
    # 这会让函数内的 `import subprocess` 拿到 patched 版本
    patch_target = "subprocess.run"

    @patch("subprocess.run")
    def test_git_status_changes(self, mock_run):
        mock_run.return_value = MagicMock(stdout="M file.txt\n")
        result = mcp_tools.handle_git_status({})
        assert "M file.txt" in result

    @patch("subprocess.run")
    def test_git_status_no_changes(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        result = mcp_tools.handle_git_status({})
        assert "No changes" in result

    @patch("subprocess.run")
    def test_git_log(self, mock_run):
        mock_run.return_value = MagicMock(stdout="abc123 commit 1\ndef456 commit 2\n")
        result = mcp_tools.handle_git_log({"limit": 5})
        assert "abc123" in result
        # 验证 limit 参数
        args = mock_run.call_args[0][0]
        assert "-5" in args[-1]

    @patch("subprocess.run")
    def test_git_log_default_limit(self, mock_run):
        mock_run.return_value = MagicMock(stdout="abc commit\n")
        mcp_tools.handle_git_log({})
        args = mock_run.call_args[0][0]
        assert "-10" in args[-1]   # default limit=10

    @patch("subprocess.run")
    def test_git_log_empty(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        result = mcp_tools.handle_git_log({})
        assert "No commits" in result

    @patch("subprocess.run")
    def test_git_status_exception(self, mock_run):
        mock_run.side_effect = FileNotFoundError("git not found")
        result = mcp_tools.handle_git_status({})
        assert "Error" in result

    @patch("subprocess.run")
    def test_docker_ps(self, mock_run):
        mock_run.return_value = MagicMock(stdout="web   Up  0:80\n")
        result = mcp_tools.handle_docker_ps({})
        assert "web" in result

    @patch("subprocess.run")
    def test_docker_ps_not_available(self, mock_run):
        mock_run.return_value = MagicMock(stdout="")
        result = mcp_tools.handle_docker_ps({})
        assert "Docker not available" in result


# ==================== 系统工具 ====================

class TestSystemTools:

    @patch("psutil.cpu_count")
    @patch("psutil.virtual_memory")
    @patch("psutil.disk_usage")
    def test_system_info(self, mock_disk, mock_vm, mock_cpu):
        # dict() 需要对象支持 _asdict() 或 _fields
        # psutil 的 disk_usage / virtual_memory 实际是 namedtuple
        from collections import namedtuple
        DiskUsage = namedtuple("DiskUsage", ["total", "used", "free", "percent"])
        Mem = namedtuple("svmem", ["total", "available", "percent", "used", "free"])

        mock_cpu.return_value = 8
        mock_vm.return_value = Mem(
            total=16 * 1024**3, available=8 * 1024**3,
            percent=50.0, used=8 * 1024**3, free=8 * 1024**3
        )
        mock_disk.return_value = DiskUsage(
            total=500 * 1024**3, used=200 * 1024**3,
            free=300 * 1024**3, percent=40.0
        )

        result = mcp_tools.handle_system_info({})
        data = json.loads(result)
        assert data["cpu_count"] == 8
        assert data["memory_total"] == 16 * 1024**3
        assert data["disk_usage"]["total"] == 500 * 1024**3
        assert "system" in data

    @patch("psutil.process_iter")
    def test_process_list(self, mock_iter):
        mock_iter.return_value = [
            MagicMock(info={"pid": 1, "name": "a", "cpu_percent": 5.0, "memory_percent": 10.0}),
            MagicMock(info={"pid": 2, "name": "b", "cpu_percent": 50.0, "memory_percent": 20.0}),
        ]
        result = mcp_tools.handle_process_list({"limit": 2})
        # 验证两个 PID 都出现
        assert "PID: 1" in result
        assert "PID: 2" in result
        # 验证排序：CPU 高的（b: 50%）在 CPU 低的（a: 5%）之前
        lines = [l for l in result.split("\n") if l.startswith("PID: ")]
        assert len(lines) == 2
        assert "Name: b" in lines[0]
        assert "Name: a" in lines[1]


# ==================== 数据工具 ====================

class TestDataTools:

    def test_json_parse_pretty(self):
        result = mcp_tools.handle_json_parse({"json": '{"x":1}', "pretty": True})
        data = json.loads(result)
        assert data["x"] == 1
        assert "\n" in result   # pretty

    def test_json_parse_compact(self):
        result = mcp_tools.handle_json_parse({"json": '{"x":1}', "pretty": False})
        assert result == '{"x": 1}'

    def test_json_parse_default_pretty(self):
        # 默认 pretty=True
        result = mcp_tools.handle_json_parse({"json": '{"x":1}'})
        assert "\n" in result

    def test_json_parse_no_input(self):
        result = mcp_tools.handle_json_parse({})
        assert "json is required" in result

    def test_json_parse_invalid(self):
        result = mcp_tools.handle_json_parse({"json": "{bad"})
        assert "Invalid JSON" in result

    def test_json_query_success(self):
        data = json.dumps({"users": [{"name": "alice"}, {"name": "bob"}]})
        result = mcp_tools.handle_json_query({"json": data, "query": "users[0].name"})
        assert "alice" in result

    def test_json_query_no_json(self):
        result = mcp_tools.handle_json_query({"query": "x"})
        assert "json and query are required" in result

    def test_json_query_no_query(self):
        result = mcp_tools.handle_json_query({"json": "{}"})
        assert "json and query are required" in result

    def test_json_query_invalid_jmespath(self):
        result = mcp_tools.handle_json_query({"json": "{}", "query": "@#$"})
        assert "Error" in result


# ==================== 时间工具 ====================

class TestTimeTools:

    def test_current_time_default_format(self):
        result = mcp_tools.handle_current_time({})
        # 2024-01-01 12:34:56 → 19 字符
        assert len(result) == 19
        assert "-" in result and ":" in result

    def test_current_time_custom_format(self):
        result = mcp_tools.handle_current_time({"format": "%Y"})
        assert len(result) == 4
        assert result.isdigit()

    def test_timestamp_to_format(self):
        # 1700000000 = 2023-11-14 22:13:20 UTC
        result = mcp_tools.handle_timestamp({"timestamp": 1700000000, "format": "%Y-%m-%d"})
        assert result.startswith("2023-11")

    def test_timestamp_now(self):
        result = mcp_tools.handle_timestamp({})
        # 13 位数字
        assert result.isdigit()
        assert len(result) >= 10


# ==================== 注册函数 ====================

class TestRegistration:

    def test_register_all_mcp_tools(self):
        mcp_tools.register_all_mcp_tools()

        all_tools = MCPToolRegistry.get_all_tools()
        # 合并所有 categories 的工具名
        tool_names = set()
        for category_tools in all_tools.values():
            tool_names.update(category_tools.keys())

        for expected in ["file_read", "file_write", "directory_list", "http_request",
                         "whoami", "git_status", "git_log", "docker_ps",
                         "system_info", "process_list", "json_parse", "json_query",
                         "current_time", "timestamp_convert"]:
            assert expected in tool_names, f"missing tool: {expected}"

        # 验证 schema 存在
        for name in ["file_read", "file_write", "http_request"]:
            entry = self._find_tool(all_tools, name)
            assert entry is not None
            # input_schema 在 entry["tool"].input_schema 里
            assert entry["tool"].input_schema is not None
            assert "type" in entry["tool"].input_schema

    def test_registered_tool_handler_callable(self):
        mcp_tools.register_all_mcp_tools()
        entry = self._find_tool(MCPToolRegistry.get_all_tools(), "file_read")
        assert callable(entry["handler"])

    def test_registered_tool_categories(self):
        mcp_tools.register_all_mcp_tools()
        all_tools = MCPToolRegistry.get_all_tools()

        # 验证分类（按 category 名）
        # 收集每个 category 中的工具名
        for category, expected_tools in [
            ("file", ["file_read", "file_write", "directory_list"]),
            ("utility", ["current_time", "timestamp_convert"]),
            ("data", ["json_parse", "json_query"]),
            ("system", ["system_info", "process_list", "whoami"]),
            ("web", ["http_request"]),
            ("development", ["git_status", "git_log", "docker_ps"]),
        ]:
            for tool_name in expected_tools:
                assert tool_name in all_tools.get(category, {}), \
                    f"missing {tool_name} in category {category}"

        # 至少这些 categories 存在
        for cat in all_tools.keys():
            # 至少有 category key
            assert isinstance(cat, str)

    @staticmethod
    def _find_tool(all_tools, name):
        """在所有 categories 中查找工具。"""
        for category_tools in all_tools.values():
            if name in category_tools:
                return category_tools[name]
        return None