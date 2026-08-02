# auto-archive PR Approval Gate（Day 20）

## 为什么需要

`release-build.yml` 的 archive-acceptance job 会自动把 errored 测试文件移到
`tests-archive/_obsolete/<ts>/` 并开一个 PR。虽然这是"自动化清理"，但：

- 任何"批量删除历史测试"都不应无 review 上 main；
- 团队里 1-2 人应负责 review，避免误删；
- 与 release tag 联动时，maintainer 在合并前最后把关。

## 配置（GitHub UI）

前往 **Repo Settings → Branches → Branch protection rules → New rule**。

### Rule 1：保护 `auto-archive/*`

> **Branch name pattern**：`auto-archive/*`
>
> ☑ **Require a pull request before merging**
>   - ☑ **Require approvals**: `1`
>   - ☑ **Dismiss stale pull request approvals when new commits are pushed**
>   - ☑ **Require review from Code Owners**
>
> ☑ **Require status checks to pass before merging**
>   - 选 `archive-acceptance`（CI job 名）
>
> ☑ **Do not allow force pushes**
>
> ☑ **Do not allow deletions**

效果：所有 `auto-archive/<ts>` 分支必须有 1 个 approval + archive-acceptance job 绿，才能 merge。

### Rule 2：CODEOWNERS（可选）

新增 `.github/CODEOWNERS`：

```
# auto-archive/* 必须有 maintainer review
/auto-archive/  @<your-org>/maintainers

# tests-archive/ 任何改动都触发 maintainer review
/tests-archive/  @<your-org>/maintainers
```

把 `CODEOWNERS` 加到 default branch 的 branch protection：

> ☑ **Require code owner review for pull requests**

效果：开 PR 时 GitHub 自动 request review from maintainers team。

### Rule 3：限制谁可以 push `auto-archive/*`

> **Restrict who can push to matching branches**
>   - 选 `Only allow specific actors to push` → `Only allow these actors to push`：
>     - 加 GitHub Actions bot 用户（`github-actions[bot]`）
>     - 加 maintainers

效果：手动 `git push origin auto-archive/foo` 会被拒；只有 CI bot 与 maintainer 能推。

## CODEOWNERS 模板

```yaml
# .github/CODEOWNERS
# Each line is a file pattern followed by one or more owners.
# Order matters; later patterns take precedence.

# Default owners for everything not matched below
*                                         @<your-org>/devs

# auto-archive PR 必须 maintainer review
/auto-archive/                            @<your-org>/maintainers
/tests-archive/                           @<your-org>/maintainers
/tools/archive_legacy.py                  @<your-org>/maintainers
/.github/workflows/release-build.yml      @<your-org>/maintainers
/.github/workflows/weekly-archive.yml     @<your-org>/maintainers
```

## 验证 checklist

跑下面的命令验证配置生效：

```bash
# 1. 看 CODEOWNERS 文件被 GitHub 正确识别
gh api repos/<org>/<repo>/contents/.github/CODEOWNERS | jq .name

# 2. 触发一次 auto-archive PR，验证 GitHub 自动请求 review
gh pr list --label auto-archive --state open
# → PR 显示 "Review required from @<your-org>/maintainers"

# 3. 检查 branch protection 状态
gh api repos/<org>/<repo>/branches/auto-archive/$(date +%s)/protection | jq .required_status_checks
# → 应含 archive-acceptance job
```

## Merge / Cleanup 流程

| 步骤 | 谁做 | 命令 |
|------|------|------|
| 1. CI 自动开 PR | `github-actions[bot]` | `gh pr create --base main` |
| 2. Maintainer review | maintainer | 在 GitHub UI 上 review |
| 3. 合并 | maintainer | `Squash and merge` |
| 4. 删除源分支 | 自动 | Merge 后 GitHub 弹提示，maintainer 点"Delete branch" |
| 5. 旧 _obsolete 清理 | release 时 | 见 [archive-acceptance.md](archive-acceptance.md) |

## 常见错误与排查

| 现象 | 排查 |
|------|------|
| auto-archive PR 没自动请求 review | `CODEOWNERS` 路径模式写错；用 `/*/auto-archive/` 不要 `/auto-archive/` |
| Maintainer 看不到 "Approve" 按钮 | 没加入团队；到 https://github.com/orgs/<org>/teams/maintainers 邀请 |
| PR 不能 merge，提示"required check failed" | archive-acceptance job 红了；看 logs |
| 手动 push 失败 | branch protection "Restrict who can push" 没加 maintainers |

## 关闭 / 调试模式

紧急情况下想跳过 review gate：

1. 临时把 `auto-archive/*` branch protection 改 `0` approvals；
2. 或用 `gh pr merge --admin`（admin 用户绕过 approval）；
3. **但记得事后恢复**！

## 相关文件

- [archive-acceptance.md](archive-acceptance.md) — 整套归档验收方法
- [release-build.yml](https://github.com/<org>/<repo>/blob/main/.github/workflows/release-build.yml) — release 工作流
- [weekly-archive.yml](../.github/workflows/weekly-archive.yml)（Day 20）— 每周日 cron
- GitHub docs: https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches