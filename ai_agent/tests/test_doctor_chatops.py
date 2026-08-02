"""tools/doctor_chatops.py 单测（Day 17）。

- payload 构建（slack / discord）的形状
- dry-run 路径不真发
- send_webhook 在 mock 下返回 HTTP 200 / 4xx 行为正确
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from tools.doctor_chatops import (
    build_slack_payload,
    build_discord_payload,
    build_payload,
    send_webhook,
    _short,
)


class FakeCheck:
    def __init__(self, name, status, message, fix=None):
        self.name = name
        self.status = status
        self.message = message
        self.fix = fix


# ---- _short ----

def test_short_truncates_with_ellipsis():
    s = _short("a" * 100, max_len=10)
    assert s.endswith("\u2026")
    assert len(s) == 10


def test_short_keeps_short_strings():
    s = _short("hi", max_len=10)
    assert s == "hi"


# ---- Slack payload ----

def test_slack_payload_has_summary_line():
    checks = [
        FakeCheck("a", "ok", "ok msg"),
        FakeCheck("b", "warn", "warn msg", fix="do X"),
        FakeCheck("c", "fail", "fail msg", fix="do Y"),
    ]
    p = build_slack_payload(checks)
    text = p["text"]
    # 3 类计数都出现
    assert "OK" in text
    assert "WARN" in text
    assert "FAIL" in text
    # fix 显示在 text
    assert "do X" in text
    assert "do Y" in text
    # blocks: header + section + context（Day 18：加了 context）
    types = [b["type"] for b in p["blocks"]]
    assert "header" in types
    assert "section" in types
    assert "context" in types


def test_slack_payload_title_includes_status():
    checks = [
        FakeCheck("a", "fail", "x"),
    ]
    p = build_slack_payload(checks)
    title = p["blocks"][0]["text"]["text"]
    assert "1 failures" in title


def test_slack_payload_title_all_ok():
    p = build_slack_payload([FakeCheck("a", "ok", "ok")])
    assert "All OK" in p["blocks"][0]["text"]["text"]


# ---- Discord payload ----

def test_discord_payload_uses_embed():
    checks = [
        FakeCheck("a", "ok", "ok"),
        FakeCheck("b", "warn", "warn"),
    ]
    p = build_discord_payload(checks)
    assert "embeds" in p
    embed = p["embeds"][0]
    assert "AI Agent Daily Health" in embed["title"]
    # color: 1 warn, 0 fail → yellow 15105570
    assert embed["color"] == 15105570


def test_discord_payload_red_when_fail():
    checks = [FakeCheck("a", "fail", "bad")]
    p = build_discord_payload(checks)
    assert p["embeds"][0]["color"] == 15158332


def test_discord_payload_green_when_all_ok():
    p = build_discord_payload([FakeCheck("a", "ok", "ok")])
    assert p["embeds"][0]["color"] == 3066993


# ---- build_payload dispatch ----

def test_build_payload_dispatches_by_channel():
    checks = [FakeCheck("a", "ok", "x")]
    s = build_payload(checks, "slack")
    d = build_payload(checks, "discord")
    assert "blocks" in s
    assert "embeds" in d


def test_build_payload_invalid_channel_raises():
    checks = [FakeCheck("a", "ok", "x")]
    with pytest.raises(ValueError):
        build_payload(checks, "telegram")


# ---- send_webhook ----

def test_send_webhook_returns_status_code():
    fake_resp = MagicMock()
    fake_resp.getcode = MagicMock(return_value=200)
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_resp):
        rc = send_webhook("https://hooks.slack.com/x", {"k": "v"})
    assert rc == 200


def test_send_webhook_4xx_returns_code():
    import urllib.error
    fake = urllib.error.HTTPError(
        url="https://hooks.slack.com/x",
        code=404,
        msg="Not Found",
        hdrs={},
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=fake):
        rc = send_webhook("https://hooks.slack.com/x", {})
    assert rc == 404


def test_send_webhook_exception_returns_zero():
    with patch("urllib.request.urlopen", side_effect=RuntimeError("net")):
        rc = send_webhook("https://hooks.slack.com/x", {})
    assert rc == 0


# ---- main CLI ----

def test_main_dry_run(capsys):
    from tools.doctor_chatops import main
    rc = main(["--channel", "slack", "--dry-run"])
    out = capsys.readouterr().out
    # 至少打出一些 payload 文本
    assert "SLACK" in out
    assert "AI Agent Daily Health" in out or "username" in out
    assert rc == 0


def test_main_skip_when_no_webhook(monkeypatch, capsys):
    from tools.doctor_chatops import main
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("SLACK_DAILY_WEBHOOK", raising=False)
    rc = main(["--channel", "slack"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no webhook url" in err


def test_main_send_success(monkeypatch, capsys):
    from tools.doctor_chatops import main

    fake_resp = MagicMock()
    fake_resp.getcode = MagicMock(return_value=200)
    fake_resp.__enter__ = MagicMock(return_value=fake_resp)
    fake_resp.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_resp):
        rc = main(["--channel", "slack", "--webhook", "https://hooks.slack.com/x"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "HTTP 200" in out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))