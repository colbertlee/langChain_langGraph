# CI Webhook 通知配置（Day 16）

`nightly-evals.yml` 在评估失败时会把通知推到 **三路并发**：

| 通道 | 用途 | 必须的 Secret | 启用开关 |
|------|------|---------------|----------|
| Slack | 团队日常告警 | `SLACK_WEBHOOK_URL` | secret 为空则自动 skip |
| Discord | 备用群 | `DISCORD_WEBHOOK_URL` | secret 为空则自动 skip |
| GitHub Issue | 不可错过 + 留痕 | `GH_TOKEN` (内置) | `NIGHTLY_OPEN_ISSUE=false` 可关 |

每个通道独立可用，缺哪个就 skip 哪个。

---

## 🚀 三步接通

### 1. Slack / Discord：创建 Incoming Webhook

- **Slack**：https://api.slack.com/messaging/webhooks → "Create New Webhook" → 复制 URL
  - 加 `bots/OAuth_Settings → Bot Token Scopes` 让 bot 能 post 到目标 channel
- **Discord**：`Server Settings → Integrations → Webhooks → New Webhook` → 复制 URL

### 2. 在 GitHub Repo 加 Secret

`Settings → Secrets and variables → Actions → New repository secret`

| Name | Value |
|------|-------|
| `SLACK_WEBHOOK_URL` | `https://hooks.slack.com/services/T000/B000/xxxxx` |
| `DISCORD_WEBHOOK_URL` | `https://discord.com/api/webhooks/123456/abcdef...` |

可选（用 var 而非 secret）：
| Name | 默认 | 含义 |
|------|------|------|
| `vars.SLACK_DEFAULT_CHANNEL` | `#ai-agent` | Slack 默认频道 |
| `vars.NIGHTLY_TEAM_LABEL` | `@ai-team` | 推送里 @ 谁 |
| `vars.NIGHTLY_OPEN_ISSUE` | `true` | `false` 时跳过 GitHub Issue |
| `vars.NIGHTLY_QUIET` | `false` | `true` 时 **完全静默** —— 用于 debug，避免刷屏 |

### 3. 验证

跑 `Actions → nightly-evals → Run workflow`，等 5 分钟：
1. 在 Actions 日志看 `Record run summary (success path)` 成功 → 表 evals 跑通
2. **手动失败一次**（改 README 把 pytest 强行跑挂）→ 验证：
   - Slack 是否收到 Block + Button
   - Discord 是否收到 embed
   - GitHub Issues 列表是否新增 issue

---

## 📦 Payload 形态

### Slack

- 标题：🚨 AI Agent nightly-evals FAILED
- 两个 blocks：header + section + actions(View Run 按钮)
- 例：

```json
{
  "channel": "#ai-agent",
  "blocks": [
    {"type": "header", "text": {"type": "plain_text", "text": "🚨 AI Agent nightly-evals FAILED"}},
    {"type": "section", "text": {"type": "mrkdwn", "text": "Repo: x/y\nOS: ubuntu-latest,windows-latest\n..."}},
    {"type": "actions", "elements": [
      {"type": "button", "text": {"type": "plain_text", "text": "View Run"}, "url": "..."}
    ]}
  ]
}
```

### Discord

```json
{
  "content": "🚨 AI Agent nightly-evals FAILED\n...",
  "embeds": [
    {"title": "🚨 AI Agent nightly-evals FAILED",
     "description": "Repo: x/y\n...",
     "color": 15158332,   // red
     "url": "<run_url>"}
  ]
}
```

### GitHub Issue

- Title：`nightly-evals failed (<run_id>)`
- Body：含 run URL + matrix 列表 + owner team
- Label：`nightly-evals`（已存在，自动加）

---

## 🔧 调试

| 现象 | 排查 |
|------|------|
| Slack 没收到 | 1. `gh repo view --json name` 确认 secret 在本 repo  <br/>2. 测试单独 `curl -X POST -d @/tmp/slack.json $URL` 看是否 200  <br/>3. Slack 的 webhook URL 自带 T/B/secret 三段，过期请重发 |
| Discord 500 | 通常是 payload 格式错；用 `curl -X POST -H 'Content-Type: application/json' -d @/tmp/discord.json $URL` 看详细错误 |
| Issue 没开 | 检查 `NIGHTLY_OPEN_ISSUE` 变量；workflow 权限 `issues: write` 是否被覆盖 |
| 通知太频繁 | `NIGHTLY_QUIET=true` 一次性屏蔽；或关对应 secret |

---

## 🛡️ 安全提示

- Webhook URL = 公开的"明文 token"。**不要**把它 commit 到代码。
- 把 webhook URL 只给"频道写权限"，不要给管理员权限。
- Slack/Discord 自身有"误发频率"防御，但仍然要做"二次校验"：建议未来加 `severity` 字段，让"严重修复"通知 ≠ "日常告警"。
