# 第一次发版完整 Runbook（一步一步截图式指南）

本 runbook 帮你**第一次**成功发布 ai-agent 到 PyPI / Docker / GitHub Release，并跑完 release.yml 的 8 个 jobs。

---

## 📋 前置 checklist

在开始之前，确认：

- [ ] 本地 wheel + sdist 已构建（已通过 `twine check`）
  ```bash
  cd ai_agent
  python -m build
  python -m twine check dist/*
  ```
- [ ] 所有测试通过（535 passed）
  ```bash
  python -m pytest tests/ -m "not slow and not integration and not network"
  ```
- [ ] 后端 CI 三层安全扫描全绿（看 PR 的 Actions）
- [ ] 你有 PyPI 账号
- [ ] 你有 GitHub 仓库 admin 权限

---

## Step 1: PyPI 账号注册

1. 打开 https://pypi.org/account/register/
2. 填用户名 / 邮箱 / 密码 → 注册
3. 验证邮箱
4. （推荐）启用 2FA

---

## Step 2: 注册 TestPyPI 账号（强烈推荐先发这里）

1. 打开 https://test.pypi.org/account/register/
2. 步骤同上

TestPyPI 是个独立环境，发错也不影响主 PyPI。

---

## Step 3: 在主 PyPI 上创建 `ai-agent` 项目（首次必须）

主 PyPI 上 `ai-agent` 还**不存在**，需要首次手动上传：

### 3.1 配 `~/.pypirc`

```bash
# Windows PowerShell
@"
[distutils]
index-servers =
    pypi
    testpypi

[pypi]
username = __token__
password = pypi-AgEIcHlwaS...你的主 PyPI token...

[testpypi]
username = __token__
password = pypi-AgEIcHlwaS...你的 TestPyPI token...
repository = https://test.pypi.org/legacy/
"@ | Out-File -Encoding utf8 ~\.pypirc
```

### 3.2 获取 token

- 主 PyPI：登录 → Account Settings → API tokens → Add API token
  - Name: `ai-agent-manual`
  - Scope: **Entire account**（首次需要）
- TestPyPI 同上

### 3.3 手动首次上传（只第一次）

```bash
cd ai_agent
python -m twine upload --repository testpypi dist/*
# 验证：https://test.pypi.org/project/ai-agent/0.1.0/

# 确认 OK 后，主 PyPI：
python -m twine upload dist/*
# 验证：https://pypi.org/project/ai-agent/
```

> ⚠️ 这次上传用的是 PyPI token（不是 OIDC），是允许的。**之后所有发版都走 OIDC trusted publishing**。

---

## Step 4: 配置 PyPI Trusted Publishing（OIDC，免 token）

### 4.1 主 PyPI

1. 登录 https://pypi.org/
2. 进入你的项目 `ai-agent` → **Publishing**（左侧菜单）
3. 点 **Add a new pending publisher**
4. 填写：

   | 字段 | 填 |
   |---|---|
   | Owner | `colbertlee` |
   | Repository name | `langChain_langGraph` |
   | Workflow filename | `release.yml` |
   | Environment name | `pypi` |

5. 保存

### 4.2 TestPyPI（可选，但推荐）

1. 登录 https://test.pypi.org/
2. 同上操作

---

## Step 5: 在 GitHub 创建 Environment `pypi`

1. 进入仓库 `https://github.com/colbertlee/langChain_langGraph`
2. **Settings** → **Environments** → **New environment**
3. Name: `pypi`
4. （可选）**Environment protection rules**：
   - **Required reviewers**：加 1-2 个 reviewer（强制人工 review 才 publish）
   - **Wait timer**：设 0 分钟（不要延迟）
5. **Save protection rules**

---

## Step 6: （可选）配置 webhook 通知

### 6.1 Slack

1. https://api.slack.com/apps → Create New App → From scratch
2. 选你的 workspace
3. **Incoming Webhooks** → **Activate** → **Add New Webhook to Workspace**
4. 选频道 → Allow
5. 复制 webhook URL

### 6.2 Discord

1. 进入目标频道 → 右上 ⚙️ → **Integrations** → **Webhooks** → **New Webhook**
2. 名字任取，复制 **Webhook URL**

### 6.3 加到 GitHub Secrets

1. 仓库 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. 添加：

   | Secret 名 | 值 |
   |---|---|
   | `SLACK_WEBHOOK_URL` | Slack webhook URL |
   | `DISCORD_WEBHOOK_URL` | Discord webhook URL |

---

## Step 7: （可选）配置 Scoop + Brew 自动更新

需要 PAT_BOT secret（cross-repo PR 用）：

1. https://github.com/settings/tokens/new
2. **Note**: `ai-agent-release-bot`
3. **Scopes**: 勾 `repo` + `workflow`
4. **Generate token** → 复制

加到 GitHub Secrets：
| Secret 名 | 值 |
|---|---|
| `PAT_BOT` | 上面生成的 token |

---

## Step 8: 打 tag 并推送（触发 release.yml）

### 8.1 确认版本号

```bash
cd E:\langChain_langGraph
git fetch origin main
git status
# 确认 working tree clean
```

### 8.2 打 tag

```bash
# v0.1.0 是 ai_agent/pyproject.toml 里写的版本号
# 保持一致很重要（release-please 通过 manifest 跟踪）
git tag -a v0.1.0 -m "Release v0.1.0

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

### 8.3 推送 tag

```bash
git push origin v0.1.0
```

---

## Step 9: 看 Actions → Release → 8 jobs

1. 打开 https://github.com/colbertlee/langChain_langGraph/actions
2. 选最新的 "Release" workflow run
3. 看 8 个 jobs 依次跑：

| # | Job | 期望耗时 | 关键检查 |
|---|---|---|---|
| 1 | `build` | 1-2 min | sdist + wheel + twine check |
| 2 | `publish-pypi` | 30s | PyPI 上有 ai-agent 0.1.0（"Verified" 标签） |
| 3 | `publish-testpypi` | skip（tag push 不触发） | — |
| 4 | `attest-verify` | 30s | Step Summary 有 attestation 信息 |
| 5 | `publish-docker` | 3-5 min | ghcr.io 有镜像 |
| 6 | `github-release` | 30s | 有 release body（draft notes） |
| 7 | `update-package-manifests` | 1 min | 自动开 scoop/brew PR（如配了 PAT_BOT） |
| 8 | `notify` | 10s | Slack/Discord 收到通知 |

### 9.1 故障排查

**Job 2 (publish-pypi) 失败：403 OIDC invalid_token**

→ 检查：
1. PyPI 项目 → Publishing → Pending publisher 是否还在（如果被前一次拒绝，需要重新加）
2. Environment name 是否**完全匹配** `pypi`（区分大小写）
3. Workflow filename 是否**完全匹配** `release.yml`（区分大小写）

**Job 5 (publish-docker) 失败：unauthorized**

→ 检查：
1. Settings → Actions → General → Workflow permissions 是否选 "Read and write permissions"
2. 或者显式给 `packages: write`（已在 release.yml 中）

**Job 7 (package-manifests) 没开 PR**

→ 检查 PAT_BOT 是否配：
1. 仓库 → Settings → Secrets → PAT_BOT 存在？
2. PAT 的 scopes 是否包含 `repo` + `workflow`？

**Job 8 (notify) 没收到消息**

→ 检查：
1. Slack/Discord webhook URL 是否正确
2. 在仓库 Actions 页面看 job log，是否有 "if: env.SLACK_WEBHOOK_URL != ''" 跳过的提示

---

## Step 10: 验证发布产物

### 10.1 PyPI

```bash
# 在新的 venv
python -m venv /tmp/verify-pypi
source /tmp/verify-pypi/bin/activate   # bash
# 或：/tmp/verify-pypi/Scripts/Activate.ps1   # PowerShell

pip install ai-agent==0.1.0
ai-agent --help
```

打开 https://pypi.org/project/ai-agent/0.1.0/ 看：
- [ ] 版本号 0.1.0 ✓
- [ ] **Verified** 标签（PEP 740 attestation）✓
- [ ] 文件列表：tar.gz + whl ✓
- [ ] Project links：Homepage / Repository / Issues 等 ✓

### 10.2 Docker

```bash
docker pull ghcr.io/colbertlee/ai-agent-console:v0.1.0
docker run --rm ghcr.io/colbertlee/ai-agent-console:v0.1.0 --help
```

### 10.3 GitHub Release

打开 https://github.com/colbertlee/langChain_langGraph/releases/tag/v0.1.0：
- [ ] Title: "Release v0.1.0" ✓
- [ ] Body: 自动生成的 CHANGELOG ✓
- [ ] Assets: `ai_agent-0.1.0.tar.gz` + `ai_agent-0.1.0-py3-none-any.whl` ✓

### 10.4 Scoop / Brew（如果配了 PAT_BOT）

到 https://github.com/colbertlee/scoop-bucket 和 https://github.com/colbertlee/homebrew-tap 看是否有自动开的 PR：
- [ ] Branch `update-ai-agent-v0.1.0` 存在 ✓
- [ ] PR title: "ai-agent: update to v0.1.0" ✓
- [ ] 手动 review + merge → 用户能 `scoop install ai-agent` / `brew install ai-agent`

---

## Step 11: （可选）配置 release-please

如果想让发版全自动化：

### 11.1 第一次手动 tag 已完成

release-please 现在能识别 `ai-agent: 0.1.0`（从 manifest）。

### 11.2 开发者改 PR workflow

1. 开发者按 [Conventional Commits](https://www.conventionalcommits.org/) 提交：
   ```bash
   git commit -m "feat: 添加 ETF 估值查询工具"
   git commit -m "fix: 修复 fallback chain timeout"
   git commit -m "feat!: 重写 LLM provider 配置（BREAKING）"
   ```

2. 合并 PR → main → `release-please.yml` 自动开 "Release PR"：
   - Title: `chore(main): release 0.2.0`
   - 内容：自动生成的 CHANGELOG + version bump 到 0.2.0

3. 维护者 review + merge Release PR → 自动：
   - 更新 `pyproject.toml` 的 `version` 到 0.2.0
   - 更新 `ai_agent/CHANGELOG.md`
   - 创建 git tag `v0.2.0`
   - 创建 GitHub Release
   - **触发 release.yml**（你刚才配的 8 jobs）→ 自动 publish 0.2.0

### 11.3 验证 release-please 工作

合并一个普通 PR 到 main，看 Actions 是否有 `Release Please` workflow run。
然后看它是否开了 Release PR（标题为 `chore(main): release X.Y.Z`）。

---

## 🎉 完成！

你的 ai-agent 现在已经：
- ✅ 发布到 PyPI（带 PEP 740 provenance）
- ✅ Docker 镜像在 GHCR
- ✅ GitHub Release 带自动 CHANGELOG
- ✅ Scoop + Brew 自动更新
- ✅ Slack/Discord 通知
- ✅ release-please 自动化下次发版

---

## 附录：常用命令速查

```bash
# 本地构建 + dry-run
cd ai_agent
python -m build
python -m twine check dist/*
python scripts/dry-run-release.py --skip-docker

# 看 PyPI 包元数据
pip show ai-agent

# 手动验证 PEP 740 attestation
pip install sigstore
python -m sigstore verify identity \
  --cert-identity 'https://github.com/colbertlee/langChain_langGraph/.github/workflows/release.yml@refs/tags/v0.1.0' \
  --cert-oidc-issuer 'https://token.actions.githubusercontent.com' \
  dist/ai_agent-0.1.0-py3-none-any.whl

# 删除 tag（出问题时回滚）
git tag -d v0.1.0
git push origin :refs/tags/v0.1.0
# PyPI 上版本不可删除（PyPI 规则），只能 yank 或上传新版本

# 看 GitHub Actions runs
gh run list --workflow=release.yml --limit=5
gh run view <run-id> --log
```