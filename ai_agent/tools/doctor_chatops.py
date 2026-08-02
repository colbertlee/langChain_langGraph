"""
Doctor ChatOps 推送（Day 17）。

为 ``daily-doctor.yml`` 提供 payload 生成 + 发送逻辑。

设计
~~~~
- 调用 ``doctor.run_doctor()`` 拿 checks；
- 按 status 分桶（ok / warn / fail），用 3 类 emoji 增强可读性；
- Slack 与 Discord 都用 embed 风格；
- 发送失败（如 webhook 404 / 401）绝不 crash —— 仅 print 警告 + 返回非零退出码。

CLI::

    python tools/doctor_chatops.py --channel slack --webhook "$SLACK_DAILY_HEALTH"
    python tools/doctor_chatops.py --channel slack --dry-run     # 仅打印 payload
    python tools/doctor_chatops.py --channel all                # Slack + Discord 全推
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============================================================
# Payload 构建
# ============================================================

STATUS_EMOJI = {
    "ok": "✅",
    "warn": "⚠️",
    "fail": "❌",
}


def _short(text: str, max_len: int = 60) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def build_slack_payload(checks: List[Any]) -> Dict[str, Any]:
    """构造 Slack incoming-webhook payload（Day 18：含 View Doctor button）。

    Blocks：
    - header：title
    - section：summary 行 + 详情（仅 fail/warn）
    - context：环境信息（hostname / 时间）
    - actions：1 个 button — "View Doctor" → /web/doctor（URL 由环境变量 ``DOCTOR_UI_URL`` 控制）
    """
    summary = {"ok": 0, "warn": 0, "fail": 0}
    for c in checks:
        summary[c.status] = summary.get(c.status, 0) + 1

    title = "🤖 AI Agent Daily Health"
    if summary["fail"] == 0:
        title += " — All OK"
    else:
        title += f" — {summary['fail']} failures"

    lines: List[str] = []
    lines.append(f"*OK*: {summary['ok']}  *WARN*: {summary['warn']}  *FAIL*: {summary['fail']}")
    lines.append("")
    fail_or_warn = [c for c in checks if c.status != "ok"]
    for c in fail_or_warn:
        emoji = STATUS_EMOJI[c.status]
        line = f"{emoji} *{c.name}*: {_short(c.message)}"
        if c.fix:
            line += f"\n   → 修: {_short(c.fix, 80)}"
        lines.append(line)

    text_body = "\n".join(lines) if lines else "_All checks passed — no warnings or failures._"

    # "View Doctor" 按钮 URL：从环境变量读，默认相对路径
    doctor_url = os.environ.get("DOCTOR_UI_URL", "http://localhost:8000/web/doctor")
    is_local = doctor_url.startswith(("http://localhost", "http://127.0.0.1"))

    actions_block: Optional[Dict[str, Any]] = None
    if not is_local:
        # 生产环境：放 button（Slack BLOCK KIT）
        actions_block = {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "🌐 View Doctor",
                        "emoji": True,
                    },
                    "url": doctor_url,
                    "style": (
                        "danger" if summary["fail"] > 0
                        else "default" if summary["warn"] > 0
                        else "primary"
                    ),
                    "action_id": "view_doctor",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "📊 View API JSON",
                        "emoji": True,
                    },
                    "url": doctor_url + ("?json=1" if "?" not in doctor_url else "&json=1"),
                    "action_id": "view_api_json",
                },
            ],
        }

    blocks: List[Dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text", "text": title}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": text_body},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"🌐 Doctor URL: `{doctor_url}`"
                        + (
                            "  _(local; Slack button omitted)_"
                            if is_local
                            else ""
                        )
                    ),
                }
            ],
        },
    ]
    if actions_block:
        blocks.append(actions_block)

    return {
        "username": "ai-agent-bot",
        "icon_emoji": ":robot_face:",
        "text": f"{title}\n\n{text_body}",  # fallback
        "blocks": blocks,
    }


def build_discord_payload(checks: List[Any]) -> Dict[str, Any]:
    """构造 Discord webhook payload。"""
    summary = {"ok": 0, "warn": 0, "fail": 0}
    for c in checks:
        summary[c.status] = summary.get(c.status, 0) + 1

    # 颜色优先级：red (fail > 0) > yellow (warn > 0 && fail == 0) > green
    if summary["fail"] > 0:
        color = 15158332  # red
    elif summary["warn"] > 0:
        color = 15105570  # yellow
    else:
        color = 3066993   # green

    lines: List[str] = []
    lines.append(f"OK: **{summary['ok']}**  WARN: **{summary['warn']}**  FAIL: **{summary['fail']}**\n")
    fail_or_warn = [c for c in checks if c.status != "ok"]
    for c in fail_or_warn:
        emoji = STATUS_EMOJI[c.status]
        line = f"{emoji} **{c.name}**: {_short(c.message)}"
        if c.fix:
            line += f"\n> 修: {_short(c.fix, 80)}"
        lines.append(line)

    description = "\n".join(lines) if lines else "All checks passed."

    return {
        "username": "ai-agent-bot",
        "embeds": [
            {
                "title": "🤖 AI Agent Daily Health",
                "description": description,
                "color": color,
            }
        ],
    }


def build_payload(checks: List[Any], channel: str) -> Dict[str, Any]:
    if channel == "slack":
        return build_slack_payload(checks)
    if channel == "discord":
        return build_discord_payload(checks)
    raise ValueError(f"unknown channel: {channel}")


# ============================================================
# HTTP 发送
# ============================================================

def send_webhook(url: str, payload: Dict[str, Any], *, timeout: float = 30.0) -> int:
    """简单 POST + 打印；失败抛 / 返回非零。"""
    import urllib.request
    import urllib.error

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.getcode() or 0
    except urllib.error.HTTPError as e:
        print(f"[warn] webhook HTTP {e.code}: {e.reason}", file=sys.stderr)
        return e.code
    except Exception as e:
        print(f"[warn] webhook failed: {e}", file=sys.stderr)
        return 0


# ============================================================
# CLI
# ============================================================

def cmd_dry_run(channels: List[str]) -> int:
    from doctor import run_doctor
    checks = run_doctor()
    for ch in channels:
        payload = build_payload(checks, ch)
        print(f"=== {ch.upper()} ===")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print()
    return 0


def cmd_send(channels: List[str], webhook_url: Optional[str]) -> int:
    """``--channel X --webhook Y`` 推一条；``--channel all`` 同时推 slack+discord。"""
    from doctor import run_doctor
    checks = run_doctor()
    rc = 0

    for ch in channels:
        if ch == "all":
            continue  # 在 --channel all 之后处理
        url = webhook_url
        if not url:
            # 从环境变量取
            url = os.environ.get(f"{ch.upper()}_DAILY_WEBHOOK") or os.environ.get(f"{ch.upper()}_WEBHOOK_URL")
        if not url:
            print(f"[skip] {ch}: no webhook url (--webhook or env var required)", file=sys.stderr)
            rc = 2
            continue
        payload = build_payload(checks, ch)
        status = send_webhook(url, payload)
        print(f"[send] {ch}: HTTP {status}")
        if status >= 400:
            rc = 1
    return rc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="doctor_chatops",
        description="Doctor 推送 → Slack/Discord（用于 CI 定时任务）",
    )
    parser.add_argument(
        "--channel",
        choices=["slack", "discord", "all"],
        default="slack",
        help="推送通道",
    )
    parser.add_argument(
        "--webhook",
        help="webhook URL（默认读 env SLACK_DISCORD_DAILY_WEBHOOK）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印 payload，不真发送",
    )
    args = parser.parse_args(argv)

    channels = ["slack", "discord"] if args.channel == "all" else [args.channel]

    if args.dry_run:
        return cmd_dry_run(channels)
    return cmd_send(channels, args.webhook)


if __name__ == "__main__":
    sys.exit(main())