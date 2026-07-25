# Branch Protection 启用指南

为强制 PR 必须通过 CI 才能 merge，需要在 GitHub 上配 Branch Protection Rules。

## 一次性配置（5 分钟）

### 1. 打开保护规则

GitHub 仓库 → **Settings** → **Branches** → **Branch protection rules** → **Add rule**

### 2. 匹配 main

- **Branch name pattern**: `main`

### 3. 推荐勾选

| 选项 | 是否勾选 | 说明 |
|---|---|---|
| Require a pull request before merging | ✅ | 禁止直接 push |
| Require approvals | ✅ (1) | 至少 1 个审 |
| Dismiss stale pull request approvals when new commits are pushed | ✅ | 新 push 失效旧审 |
| Require status checks to pass before merging | ✅ | **核心** |
| Require branches to be up to date before merging | ✅ | 必须 rebase |
| Require conversation resolution before merging | ✅ | 必须解决 review 注释 |
| Include administrators | ⚠️ | 自己 PR 也要审（推荐勾选）|
| Allow force pushes | ❌ | 禁止 |
| Allow deletions | ❌ | 禁止 |

### 4. 选 Status Checks

在 **Require status checks to pass** 下拉里选（必须**先跑过一次 CI** 才会有这些选项）：

- ✅ `e2e` — Playwright E2E + Visual Regression
- ✅ `build` — Production Build
- ✅ `type-check` — TypeScript Check
- ✅ `workflow-lint` — Workflow Lint
- ✅ `security` — Security Audit（critical/high 必过）
- ⬜ `test` — 单独不勾（已包含在 build 链路里）
- ⬜ `visual-baseline` — 不勾（仅 main 跑）

### 5. 保存

点 **Create** / **Save changes**。

## 脚本化配置（用 gh CLI 或 API）

### 方法 A：gh CLI（GitHub 推荐）

```bash
# 安装：winget install GitHub.cli

# 登录
gh auth login

# 启用 protection（一条命令搞定）
gh api \
  --method PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/OWNER/REPO/branches/main/protection \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "e2e",
      "build",
      "type-check",
      "workflow-lint",
      "security"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismissal_restrictions": {},
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
EOF
```

### 方法 B：Node 脚本（cross-platform）

```bash
node scripts/setup-branch-protection.mjs
```

### 方法 C：Terraform

```hcl
resource "github_branch_protection" "main" {
  repository_id = github_repository.example.id
  pattern       = "main"

  required_status_checks {
    strict = true
    contexts = [
      "e2e",
      "build",
      "type-check",
      "workflow-lint",
      "security",
    ]
  }

  required_pull_request_reviews {
    dismiss_stale_reviews = true
    required_approving_review_count = 1
  }

  enforce_admins = true
  required_linear_history = true
  requires_conversation_resolution = true
}
```

## 验证配置

```bash
gh api /repos/OWNER/REPO/branches/main/protection | jq '.required_status_checks.contexts'
```

应输出 5 个 check 名。

## 跳过规则（紧急情况）

配了保护后仍可能需要紧急 hotfix：
- 用 **admin** 权限才能绕过（enforce_admins=true 时）
- 或临时把 `enforce_admins` 改成 false

## 故障排查

| 现象 | 排查 |
|---|---|
| Status checks 选项是空的 | 必须先 push 一次让 CI 跑过，选项才出现 |
| PR 显示 "X is expected" 但 X 是绿色 | 因为 branch 不 up-to-date；点 "Update branch" 即可 |
| 看不到 Required reviewers 选项 | 仓库不是 PR required 状态；先勾选 Require a pull request |
