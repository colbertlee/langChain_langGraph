"""
Demo MCP Server stdio JSON-RPC 测试

通过 subprocess 启动 `python -m ai_agent.mcp_servers.demo_server`，
手写 JSON-RPC initialize / tools/list / tools/call 三步，
验证 stdio 模式能跑通协议。

不依赖第三方测试库，只用 stdlib subprocess + json。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


# ai_agent/ 的父目录（即仓库根）需要进 path 才能 import ai_agent.mcp_servers.demo_server
REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _spawn_demo_server() -> subprocess.Popen:
    """启动 demo server 子进程，stdin=PIPE / stdout=PIPE / stderr=PIPE"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.Popen(
        [sys.executable, "-m", "ai_agent.mcp_servers.demo_server"],
        cwd=str(REPO_ROOT),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )


def _send(proc: subprocess.Popen, payload: dict, expect_response: bool = True):
    """发一条 newline-delimited JSON-RPC 消息，返回一条响应（可选）

    MCP stdio server 用 newline-delimited JSON（每条 JSON \\n 结尾），
    而不是 LSP 的 Content-Length: 头。
    """
    body = json.dumps(payload) + "\n"
    assert proc.stdin is not None
    proc.stdin.write(body)
    proc.stdin.flush()
    if not expect_response:
        return None
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line:
        raise RuntimeError("server closed stdout unexpectedly")
    return json.loads(line)


def _initialize(proc: subprocess.Popen) -> None:
    """完成 initialize 握手 + 发 notifications/initialized 通知"""
    _send(proc, {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0.1"},
        },
    })
    # MCP 1.x 协议要求：initialize 后必须立刻发 notifications/initialized
    _send(proc, {
        "jsonrpc": "2.0",
        "method": "notifications/initialized",
    }, expect_response=False)


@pytest.fixture
def server_proc():
    proc = _spawn_demo_server()
    try:
        yield proc
    finally:
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_initialize_handshake(server_proc: subprocess.Popen):
    """Step 1: initialize —— 验证 server 返回 serverInfo 与协议版本"""
    resp = _send(server_proc, {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0.1"},
        },
    })
    assert resp.get("jsonrpc") == "2.0"
    assert resp.get("id") == 1
    result = resp.get("result", {})
    info = result.get("serverInfo", {})
    assert info.get("name") == "demo-mcp-server"
    assert "tools" in result.get("capabilities", {})


def test_list_tools_returns_five(server_proc: subprocess.Popen):
    """Step 2: tools/list —— 验证 5 个工具都注册了"""
    _initialize(server_proc)
    resp = _send(server_proc, {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    })
    tools = resp["result"]["tools"]
    names = sorted(t["name"] for t in tools)
    assert names == ["echo", "random_number", "reverse_text", "sha256_hash", "word_count"]


@pytest.mark.parametrize("tool_name,args,expected", [
    ("echo", {"text": "hi"}, "hi"),
    ("reverse_text", {"text": "abc"}, "cba"),
    ("sha256_hash", {"text": "abc"}, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    ("random_number", {"min": 1, "max": 1}, "1"),
    ("word_count", {"text": "hello world\nfoo"}, None),  # 见下方断言
])
def test_call_tool_basic(server_proc: subprocess.Popen, tool_name, args, expected):
    """Step 3: tools/call —— 调每个工具，验证输出"""
    _initialize(server_proc)
    resp = _send(server_proc, {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    })

    assert "result" in resp, f"unexpected response: {resp}"
    content = resp["result"]["content"]
    assert content and content[0]["type"] == "text"
    text = content[0]["text"]

    if tool_name == "word_count":
        # word_count 输出形如 "chars=17 words=3 lines=2"
        assert text.startswith("chars=")
        assert " words=3" in text
        assert " lines=2" in text
    else:
        assert text == expected


def test_call_tool_unknown(server_proc: subprocess.Popen):
    """未知工具：handler 返回 Error 字符串"""
    _initialize(server_proc)
    resp = _send(server_proc, {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "no_such_tool", "arguments": {}},
    })
    text = resp["result"]["content"][0]["text"]
    assert "unknown tool" in text