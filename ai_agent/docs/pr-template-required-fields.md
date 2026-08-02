# PR Template Checklist 强制必填（Day 22）

## 问题

GitHub Actions **没有原生"PR template checkbox 必填"**。
PR template 只能"建议" reviewer 填，但无法阻止跳过。

我们的 auto-archive PR 风险特别大（批量移文件），必须 enforce。

## 解决方案（Day 22）

用 **GitHub branch protection + 配套 CI 校验脚本** 两层保护。

### 第一层：Branch Protection

`Repo Settings → Branches → Add rule`：

> **Branch name pattern**: `auto-archive/*`
>
> ☑ **Require a pull request before merging**
>   - ☑ **Require approvals**: `1`
>   - ☑ **Dismiss stale pull request approvals when new commits are pushed**
>
> ☑ **Require status checks to pass before merging**
>   - 选 `pr-metadata-check`（见下）
>
> ☑ **Do not allow force pushes**
>
> ☑ **Do not allow deletions**
>
> ☑ **Require linear history**

效果：所有 `auto-archive/*` 分支必须有 approval + `pr-metadata-check` 通过。

### 第二层：CI 校验脚本

新增 `tools/check_pr_metadata.py`，检查 PR body 含关键 section：

```
🚨 Maintainer Review Required
## Summary
## 涉及文件
## Checklist
```

缺任何一项 → exit 1 → CI red → branch protection 阻止 merge。

## CI 接入

`.github/workflows/release-build.yml` 的 auto-archive PR step 之后：

```yaml
- name: PR metadata check
  if: success()
  shell: bash
  env:
    GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    # 找最近开的 auto-archive PR
    PR_NUMBER=$(gh pr list --label auto-archive --state open --json number --jq '.[0].number // empty')
    if [ -z "$PR_NUMBER" ]; then
      echo "no open auto-archive PR"
      exit 0
    fi
    python tools/check_pr_metadata.py \
      --repo "${{ github.repository }}" \
      --pr "$PR_NUMBER"
```

## 自动 checklist 必填的工作流

由于 GitHub 不支持原生 enforce，我们有三种方案组合：

### A. PR Template 显式 `<input type="checkbox">`（HTML）

```html
<!-- .github/PULL_REQUEST_TEMPLATE/auto-archive.md -->
<input type="checkbox" required> 我已确认这些文件应清理
<input type="checkbox" required> 旧文件 git history 仍可用
```

> ⚠️ **限制**：GitHub 在 PR 页面会渲染为 ✅/☐ 框但 **不会 enforce required**。用户提交时空框也 OK。

### B. Branch Protection + CI script（Day 22 推荐）

[PR template 文件](../.github/PULL_REQUEST_TEMPLATE/auto-archive.md) 含必填占位符；
CI 脚本 `tools/check_pr_metadata.py` 校验；branch protection 强制通过 CI。

### C. GitHub Action（替代方案）

如不愿写自己的校验脚本，可用：

- `mheap/action-required-but-optional@v1`
- `KostiantynM/required-checklist@v1`

但这两个 action 与 PR title / body 配合也较弱；不如 B 方案可控。

## 完整配置 checklist

跑下面的命令验证所有配置生效：

```bash
# 1. CODEOWNERS 识别
gh api repos/<org>/<repo>/contents/.github/CODEOWNERS | jq .name

# 2. Branch protection 已启用
gh api repos/<org>/<repo>/branches/auto-archive/main/protection | jq .required_status_checks

# 3. PR template 路径正确
gh api repos/<org>/<repo>/contents/.github/PULL_REQUEST_TEMPLATE/auto-archive.md | jq .name

# 4. 触发一次 auto-archive PR，校验 metadata
gh pr list --label auto-archive --state open
PR=$(gh pr list --label auto-archive --state open --json number --jq '.[0].number')
python tools/check_pr_metadata.py --repo <org>/<repo> --pr $PR
```

## 误报 / 边缘情况

| 现象 | 修复 |
|------|------|
| "missing 4 phrases" 但 PR body 都有 | PR body 含 markdown 高亮但 plain text 缺失——用 raw body 检查 |
| maintainer approve 后 merge 仍失败 | pr-metadata-check job 没运行；看 Actions tab |
| 第三方提交（fork）的 PR body 校验 | GitHub 限制；要求 contributor 先 merge 到本地再开 PR |
| 校验脚本运行时 gh 未登录 | `gh auth login` 或 `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` |

## 关闭 / 紧急绕过

紧急情况下想跳过校验：

```bash
gh pr merge <PR_NUMBER> --admin   # admin 绕过
```

但**事后必须恢复**：把校验脚本启用。