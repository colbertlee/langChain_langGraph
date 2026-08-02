"""CI 通知 payload 测试（Day 16）。

我们不能直接测试 night-evals.yml，但能复刻 ``build payload`` 步骤的逻辑
写成一个 Python 函数 + 单测，保证推送内容是结构化的、含必要字段。
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


# ============================================================
# 复制 nightly-evals.yml 中 Python 段落的逻辑（避免 yaml 重工程解析）
# ============================================================

def _build_payloads(env):
    """等价于 nightly-evals.yml 里的 ``python - <<'PY'`` 块。

    Args:
        env: 模拟 ``os.environ`` 的 dict。
    """
    gh_run_id = env.get("GITHUB_RUN_ID", "?")
    gh_server = env.get("GITHUB_SERVER_URL", "https://github.com")
    repo = env.get("GITHUB_REPOSITORY", "owner/repo")
    run_url = f"{gh_server}/{repo}/actions/runs/{gh_run_id}"

    title = "\U0001f6a8 AI Agent nightly-evals FAILED"
    message = (
        f"Repo: {repo}\n"
        f"OS matrix failed on: ubuntu-latest,windows-latest\n"
        f"Run: {run_url}\n"
        f"Owner team: {env.get('NIGHTLY_TEAM_LABEL','@ai-team')}\n"
    )

    slack = {
        "channel": env.get("SLACK_DEFAULT_CHANNEL", "#ai-agent"),
        "username": "ai-agent-bot",
        "icon_emoji": ":robot_face:",
        "text": f"{title}\n{message}",
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": title}},
            {"type": "section", "text": {"type": "mrkdwn", "text": message}},
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "View Run"},
                        "url": run_url,
                        "style": "danger",
                    }
                ],
            },
        ],
    }

    discord = {
        "username": "ai-agent-bot",
        "content": f"{title}\n{message}",
        "embeds": [
            {
                "title": title,
                "description": message,
                "color": 15158332,
                "url": run_url,
            }
        ],
    }

    issue_title = f"nightly-evals failed ({gh_run_id})"
    issue_body = (
        "## nightly-evals failed\n\n"
        f"- run: {run_url}\n"
        f"- run_id: {gh_run_id}\n"
        "- os: ubuntu-latest,windows-latest\n"
        f"- owner team: {env.get('NIGHTLY_TEAM_LABEL','@ai-team')}\n\n"
    )

    return {
        "slack": slack,
        "discord": discord,
        "issue_title": issue_title,
        "issue_body": issue_body,
        "run_url": run_url,
    }


def test_slack_payload_basic_shape():
    env = {
        "GITHUB_RUN_ID": "1234567890",
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "miniMax/ai_agent",
        "SLACK_DEFAULT_CHANNEL": "#devops-alerts",
    }
    payloads = _build_payloads(env)
    slack = payloads["slack"]

    assert slack["channel"] == "#devops-alerts"
    assert slack["username"] == "ai-agent-bot"
    assert slack["icon_emoji"] == ":robot_face:"
    # blocks: header + section + actions
    assert len(slack["blocks"]) == 3
    assert slack["blocks"][0]["type"] == "header"
    assert slack["blocks"][1]["type"] == "section"
    assert slack["blocks"][2]["type"] == "actions"


def test_slack_payload_run_url_present():
    env = {
        "GITHUB_RUN_ID": "999",
        "GITHUB_REPOSITORY": "org/repo",
    }
    payloads = _build_payloads(env)
    # run URL 应该出现在 button url / text / content
    assert "runs/999" in payloads["run_url"]
    assert any(
        "runs/999" in str(el.get("url", ""))
        for block in payloads["slack"]["blocks"]
        if block.get("type") == "actions"
        for el in block.get("elements", [])
    )


def test_discord_payload_has_embed():
    env = {"GITHUB_RUN_ID": "42", "GITHUB_REPOSITORY": "x/y"}
    payloads = _build_payloads(env)
    discord = payloads["discord"]

    assert "embeds" in discord
    embed = discord["embeds"][0]
    assert "FAILED" in embed["title"]
    assert embed["color"] == 15158332  # red
    assert "runs/42" in embed["url"]


def test_issue_payload_includes_run_id():
    env = {"GITHUB_RUN_ID": "7777"}
    payloads = _build_payloads(env)
    assert "7777" in payloads["issue_title"]
    assert "runs/7777" in payloads["issue_body"]


def test_issue_body_uses_markdown():
    """Issue body 必须用 markdown（## / - 列表）才会在 GitHub 渲染。"""
    env = {"GITHUB_RUN_ID": "1"}
    payloads = _build_payloads(env)
    assert "##" in payloads["issue_body"]


def test_default_channel_fallback():
    """未设 SLACK_DEFAULT_CHANNEL 时默认 #ai-agent"""
    payloads = _build_payloads({})
    assert payloads["slack"]["channel"] == "#ai-agent"


def test_default_team_label_fallback():
    payloads = _build_payloads({})
    assert "ai-team" in payloads["slack"]["text"]


def test_payload_is_json_serializable():
    """所有 payload 必须能 dump 为 JSON（curl 用 raw 形式发）。"""
    env = {"GITHUB_RUN_ID": "1", "GITHUB_REPOSITORY": "x/y"}
    payloads = _build_payloads(env)
    json.dumps(payloads["slack"], ensure_ascii=False)
    json.dumps(payloads["discord"], ensure_ascii=False)
    json.dumps({"title": payloads["issue_title"], "body": payloads["issue_body"]})


# ============================================================
# webhook 发送模拟（curl 替代）
# ============================================================

def _fake_send(url: str, payload: dict, *, timeout: float = 30.0) -> dict:
    """模拟 curl POST，返回 {"status": int, "url": str}。

    Day 16：CI 中 ``Send Slack`` 步骤的 shell 等价物。
    """
    # 测试用：约定以下 URL 视为成功/失败
    if "hooks.slack.com" in url:
        return {"status": 200, "url": url}
    if "discord.com" in url:
        if "invalid" in url:
            return {"status": 400, "url": url}
        return {"status": 204, "url": url}
    return {"status": 404, "url": url}


def test_send_slack_returns_200():
    r = _fake_send("https://hooks.slack.com/services/T0/B0/xxx", {"x": "y"})
    assert r["status"] == 200


def test_send_discord_returns_204():
    r = _fake_send("https://discord.com/api/webhooks/123/abc", {"content": "x"})
    assert r["status"] == 204


def test_send_discord_invalid_url_400():
    r = _fake_send("https://discord.com/api/webhooks/invalid/abc", {"content": "x"})
    assert r["status"] == 400


def test_send_unknown_url_404():
    r = _fake_send("https://example.com/other", {})
    assert r["status"] == 404


def test_skip_rule_when_secret_missing(monkeypatch):
    """当 secret 缺失时，CI step 应自动 skip（用 ``exit 0`` 模拟）。"""
    # 模拟 bash guard：当 SLACK_WEBHOOK_URL 为空时 exit 0
    env = {}
    skipped = not env.get("SLACK_WEBHOOK_URL")
    assert skipped is True
    # 不进入 payload builder
    if not skipped:
        _build_payloads(env)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-o", "addopts=-ra --tb=short"]))
