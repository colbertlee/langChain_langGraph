# CI/CD 推送指南

## GitHub Secrets 配置（可选，但强烈推荐）

前往 GitHub 仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**。

### 必填（如需通知）

| Secret 名称 | 获取方式 | 用途 |
|---|---|---|
| `SLACK_WEBHOOK_URL` | Slack → Apps → Incoming Webhooks | 推送 weekly upgrade 报告到 Slack |
| `DISCORD_WEBHOOK_URL` | Discord 频道 → 编辑 → Integrations → Webhooks | 推送 weekly upgrade 报告到 Discord |

### 自动开 Issue（可选）

workflow 默认 `OPEN_ISSUE_ON_MAJOR=true`，会自动开 issue。
若不想自动开，在仓库 → Variables → Actions 加 `OPEN_ISSUE_ON_MAJOR=false`。

### Slack webhook 配置步骤

1. 打开 https://api.slack.com/apps → **Create New App** → From scratch
2. 选你的 workspace
3. 左侧 **Incoming Webhooks** → 打开 **Activate Incoming Webhooks**
4. **Add New Webhook to Workspace** → 选频道 → **Allow**
5. 复制生成的 webhook URL（如 `https://hooks.slack.com/services/T.../B.../...`）
6. 粘贴到 GitHub Secrets

### Discord webhook 配置步骤

1. 进入目标频道 → 右上 ⚙️ → **Integrations** → **Webhooks** → **New Webhook**
2. 名字任取（如 "GitHub Actions"），复制 **Webhook URL**
3. 粘贴到 GitHub Secrets

### 验证

push 任意 commit 后看 workflow 是否触发；weekly-upgrades 也能在 Actions 页面 **Run workflow** 手动触发验证 webhook。

---

## 第一次推送（完整 walkthrough）

### Step 0: 前置准备（一次性）

- [ ] Node 20+ 已装
- [ ] Git 已配 user.name / user.email
- [ ] GitHub 仓库存在，origin = `https://github.com/<owner>/<repo>.git`
- [ ] （可选）已配 Slack / Discord webhook → 见上面「GitHub Secrets 配置」

### Step 1: 验证本地构建

```bash
cd e:\langChain_langGraph\web_console
npm ci --no-audit --no-fund   # 干净安装
npm run check                  # tsc 0 错误
npm test                       # 41/41 通过
npm run build                  # 0 错误
npm run lint:workflows         # workflow lint 0 错误
```

### Step 2: 生成视觉回归 baseline（一次性）

> ⚠️ 必须先做，否则 CI 自动生成的 baseline 会包含本地 Chromium 的私有字体差异。

```bash
npm run e2e:install            # 下载 Chromium (~150MB)
npm run e2e:baseline:win       # Windows；Linux/macOS: npm run e2e:baseline
```

生成的 baseline 在 `web_console/e2e/visual.spec.ts-snapshots/*.png`。

### Step 3: 提交所有改动

```bash
cd e:\langChain_langGraph
git status                     # 检查 .gitignore 排除正确
git add .github web_console .gitignore
git status                     # 确认没有 ai_agent/uploads 实际文件
git commit -m "ci: GitHub Actions workflow + visual regression + cache + weekly upgrades

- ci.yml: 7 jobs (security / workflow-lint / type-check / test / visual-baseline / e2e / build)
- 4-layer cache: npm + vite prebundle + playwright browsers + dist 产物
- e2e/visual.spec.ts: 7 个 toHaveScreenshot 用例
- weekly-upgrades.yml: 每周一 09:00 UTC 依赖升级检查 + Slack/Discord 通知
- release-drafter: PR label 自动 changelog
- deploy.yml: GitHub Pages + 可选 S3 + 部署通知
- scripts/check-upgrades.mjs: 升级检测工具
- .gitignore: ai_agent/uploads/* 排除 + .gitkeep 保留
"
```

### Step 4: 推送并触发第一次 CI

```bash
git push origin main
```

打开 https://github.com/<owner>/<repo>/actions 看 5 jobs 跑起来。

### Step 5: 验证 webhook（可选）

1. 进入 Actions → `Weekly Upgrades` → **Run workflow** → 选 main → Run
2. 等 10s，看 Slack/Discord 是否收到消息
3. 如果没收到：检查 Secret 是否配对（名字一字不差）

## 第一次 CI 行为

Push 后 GitHub Actions 自动跑：

| Job | 耗时 | 关键产物 |
|---|---|---|
| type-check | ~15s | — |
| test | ~25s | coverage/ |
| e2e | ~120s (cold) / ~40s (warm) | playwright-report/ |
| build | ~30s (cold) / ~10s (warm) | dist/ |
| upgrade-check | ~10s | upgrade-report.json |

冷启动 (cold) 总耗时 ≈ 200s。warm cache 后 ≈ 40s。

## 视觉回归 baseline 生成

CI 的 e2e job 第一次跑会**自动创建 baseline**（`e2e/**/*-snapshots/*.png`），
因为 baseline 文件不存在会被认为是新增 pass。
第二次起才做 diff 比对。

> ⚠️ 推荐：**本地**先跑一遍生成 baseline 再 commit，否则 CI 会自动生成
> "看不到真正 baseline" 的初始状态。

### 本地生成 baseline

```bash
cd e:\langChain_langGraph\web_console
npm run e2e:install           # 装 chromium
npm run e2e -- visual.spec.ts # 自动生成 e2e/visual.spec.ts-snapshots/*.png

# 提交 baseline
git add web_console/e2e/visual.spec.ts-snapshots/
git commit -m "test: add visual regression baseline"
git push
```

### 更新 baseline

```bash
# 当 UI 故意改动时
npx playwright test visual.spec.ts --update-snapshots
git add web_console/e2e/visual.spec.ts-snapshots/
git commit -m "test: update visual baseline"
```

## 依赖升级通知

weekly-upgrades.yml 通过 GitHub Step Summary 展示报告。
如需 Slack/Discord 通知：在 GitHub Repo → Settings → Secrets and variables → Actions
添加 `SLACK_WEBHOOK_URL` 或 `DISCORD_WEBHOOK_URL`，见 [webhook 配置](#webhook-配置)。

## 回滚

CI 失败时只需 revert commit 或 push fix。**不要** push --force 到 main。

## 故障排查

| 症状 | 检查 |
|---|---|
| e2e 跑不起来 | `npm run e2e:install`；再 `npm run e2e` 看本地报错 |
| 视觉回归大量失败 | 检查 baseline 是否过期 `--update-snapshots` |
| Playwright 缓存命中率低 | 调整 cache key（hashFiles 加更多依赖源文件）|
| CI 超时 | 检查 Actions → 找到具体 job 增加 timeout-minutes |
