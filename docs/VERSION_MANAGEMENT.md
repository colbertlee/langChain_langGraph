# VERSION_MANAGEMENT.md · 版本与发布管理规范

> 本文件是项目"版本号如何变化、tag / release / 分支如何打、孤儿分支如何清理、
> 主分支如何保护"的**唯一权威 SOP**。
>
> 适用仓库:`colbertlee/langChain_langGraph`(镜像:`gitee.com/colbertlee/langChain_langGraph`)
> 适用版本:**v2.0.7 起**
> 最近更新:2026-09-03(v2.0.7 release 后,新增 §7.5 / §7.6)

---

## 目录

1. [版本号约定](#1-版本号约定)
2. [CHANGELOG 维护](#2-changelog-维护)
3. [本地打 tag 的流程](#3-本地打-tag-的流程)
4. [推送到 GitHub](#4-推送到-github)
5. [创建 GitHub Release](#5-创建-github-release)
6. [Gitee 镜像同步](#6-gitee-镜像同步)
7. **发布后清理(本文件重点)**
   - §7.1 [删除 orphan 分支](#71-删除-orphan-分支)
   - §7.2 [同步本地 tag 与远端 tag](#72-同步本地-tag-与远端-tag)
   - §7.3 [本地分支与远端对齐](#73-本地分支与远端对齐)
   - §7.4 [release source of truth:tag](#74-release-source-of-truthtag)
   - §7.5 [Branch protection rules(分支保护)](#75-branch-protection-rules分支保护)
   - §7.6 [新增:Orphan Branch Cleanup SOP](#76-新增orphan-branch-cleanup-sop)
8. [常见问题](#8-常见问题)

---

## 1. 版本号约定

采用 [Semantic Versioning 2.0.0](https://semver.org/),格式 `MAJOR.MINOR.PATCH`:

| 段位 | 触发条件 | 示例 |
|---|---|---|
| MAJOR | 破坏性 API 变更 / 架构重构 | v1.x → v2.0 |
| MINOR | 新增向后兼容的功能 | v2.0 → v2.1 |
| PATCH | 修复 / 文档 / 性能(向后兼容) | v2.0.6 → v2.0.7 |

**清理 / 重构 / 性能** 等无功能变更的 release 也算 PATCH,详见 §1.1。

### 1.1 特殊 tag 后缀

允许在 PATCH 后追加字母数字后缀表达里程碑含义,**只**用于源码仓库里程碑标记,
**不带二进制产物**(二进制产物在 `ai-agent-releases` 仓库):

| 后缀格式 | 含义 | 是否进 Gitee | GitHub Release 资产 |
|---|---|---|---|
| `vX.Y.Z` | 正式发布 | ✅ | ✅ |
| `vX.Y.Z-cleanup-verified` | 清理后 QA 里程碑 | ✅ | 仅 milestone tag,无二进制 |
| `vX.Y.Z-rcN` | 预发布候选 | ✅ | prerelease=true |
| `vX.Y.Z-hotfix.N` | 热修复 | ✅ | ✅ |

> ⚠️ **强制规则**:任何带后缀的 tag,不得绑定二进制资产(`.zip` / `.exe` / `.whl`)。
> 产物归档一律走 [`colbertlee/ai-agent-releases`](https://github.com/colbertlee/ai-agent-releases)。

---

## 2. CHANGELOG 维护

### 2.1 入口文件

- 顶层 [`CHANGELOG.md`](../CHANGELOG.md) — 用户可见
- 本文件 — 流程可见

### 2.2 每版本条目结构

```markdown
## [vX.Y.Z] - YYYY-MM-DD

### Added
- 新功能列表

### Changed
- 行为变更

### Fixed
- 修复

### Removed
- 删除项(含 cleanup)

### Migration
- vX.Y.(Z-1) → vX.Y.Z 必须执行的步骤
```

> CHANGELOG 与 release body 可以内容相同,但 release body 额外需要带 **verification 表**。

---

## 3. 本地打 tag 的流程

```powershell
# 1. 确认 working tree 干净
git status

# 2. 确认 master 已与 origin 同步
git fetch origin master
git log --oneline master..origin/master   # 必须为空

# 3. 打 annotated tag(推荐)
git tag -a vX.Y.Z -m "release: vX.Y.Z - <一句话摘要>"
git tag -a vX.Y.Z-cleanup-verified -m "milestone: post-cleanup QA verified"   # 清理后里程碑

# 4. 校验 tag
git show vX.Y.Z --stat | Select-Object -First 20
git tag -l --points-at HEAD
```

> ❗ **不允许 lightweight tag**。`git push --follow-tags` 不会被本 SOP 采用,
> 理由是 tag 必须显式 push(见 §4)。

---

## 4. 推送到 GitHub

### 4.1 推 master

```powershell
git push origin master
```

若报 `fetch first` 或 `non-fast-forward`,**禁止 `--force`**,按 §7.3 处理。

### 4.2 推 tag

```powershell
git push origin vX.Y.Z
git push origin vX.Y.Z-cleanup-verified
```

### 4.3 推 release 分支(可选,merge 后会自动留下 ref)

仅在需要"按分支锚定 release"时使用,命名:`release/vX.Y.Z[-suffix]`:

```powershell
git push -u origin release/vX.Y.Z-cleanup-verified
```

merge 后 GitHub 会保留该 ref,作为可追溯审计线;§7.6 解释如何清理。

---

## 5. 创建 GitHub Release

### 5.1 标准发布动作

```powershell
$env:GH_TOKEN = "<github_pat_with_repo_scope>"
gh release create vX.Y.Z `
  --target master `
  --title "AI Agent vX.Y.Z — <一句话>" `
  --notes-file release_notes/vX.Y.Z.md `
  ./dist/*
```

### 5.2 fallback:curl(无 gh CLI 时)

见 [`docs/RELEASE_FALLBACK.md`](RELEASE_FALLBACK.md)(本仓库 v2.0.7 时代已无
`upload_to_github_release.py`,改用 curl + `--data-binary @file` 调用
`POST /releases` 与 `POST /releases/{id}/assets`)。release body 用 UTF-8
文本文件通过 `--data-binary @-` 传入,避免 PowerShell 引号转义陷阱。

### 5.3 milestone release(无二进制)

```powershell
gh release create vX.Y.Z-cleanup-verified `
  --target <commit-sha> `
  --title "vX.Y.Z-cleanup-verified — Post-cleanup QA milestone" `
  --notes-file release_notes/vX.Y.Z-cleanup-verified.md `
  --latest=false
```

> 注意:`--target` 必须传 **commit SHA**,不要传分支名,以免远端 HEAD 漂移。

### 5.4 上传二进制(产物仓库)

二进制(`zip` / `whl` / `exe`) **不** 上传到本仓库,改用:

```
gitee-binaries → https://gitee.com/colbertlee/ai-agent-releases
```

发布脚本路径:`scripts/release/publish_binaries.py`(待补)。

---

## 6. Gitee 镜像同步

本仓库使用 Gitee 作为国内镜像,默认分支 `master`。

```powershell
git push gitee master
git push gitee vX.Y.Z vX.Y.Z-cleanup-verified
git push gitee release/vX.Y.Z-cleanup-verified
```

> ⚠️ 不要在 Gitee 上创建 Release。GitHub 是 source of truth,Gitee 仅镜像源码 + tag。

---

## 7. 发布后清理 ⭐

> **为什么必须有这一节?** v2.0.7 实战教训:
> - 远端同时出现 `master`、`main` 两个分支(后者是 GitHub 仓库初始化默认创建的)
> - 多余的 `chore/project-cleanup-backup` 本地备份分支长期残留
> - 孤儿 `release/v2.0.7-cleanup-verified` 分支 merge 后无人清理
>
> 本节把"发布完要做什么"明文化,避免下次再手动摸索。

### 7.1 删除 orphan 分支

**orphan 分支定义**:不与 `master` 同步历史、对当前 release 生命周期无用、merge 后无人 review 的分支。

#### 7.1.1 一次性清点脚本

```powershell
# 列出所有本地与远端分支 + 它们的提交摘要
git for-each-ref --format='%(refname:short) %(committerdate:short) %(subject)' refs/heads refs/remotes/origin | Sort-Object
```

#### 7.1.2 删除条件检查清单(全部 ✅ 才允许删)

- [ ] 分支 HEAD 的所有提交内容都已被 `master` 包含(`git log master..branch` 为空)
- [ ] 分支没有 release / tag 引用(`git tag --points-at branch` 为空)
- [ ] 没有 worktree 占用(`git worktree list` 中没有该分支)
- [ ] 没有 `branch.<name>.remote` 远端追踪配置
- [ ] reflog 显示该分支仅一次性创建(无频繁切换)

满足以上条件,执行:

```powershell
# 本地分支
git branch -D <orphan-name>

# 远端分支
git push origin --delete <orphan-name>
# 或者
git push origin :<orphan-name>
```

#### 7.1.3 不允许删除的分支

- `master`
- 当前 release 对应的 tag 名(如 `vX.Y.Z-cleanup-verified` 本身)
- 任何 `protected: true` 的分支(由 GitHub 分支保护保证)

### 7.2 同步本地 tag 与远端 tag

```powershell
# 查看 tag 漂移
git ls-remote origin 'refs/tags/*'
git for-each-ref --format='%(refname:short) %(objectname:short)' refs/tags
```

如果本地 tag 与远端指向不同 commit:

```powershell
# 删除本地 tag(不影响远端)
git tag -d vX.Y.Z

# 重新拉取(远端为准)
git fetch origin refs/tags/vX.Y.Z:refs/tags/vX.Y.Z
```

> ⚠️ **永远不要**强制覆盖远端 tag(`git push origin -f tag vX.Y.Z`)— release 与 tag 已绑定,
> 强推会破坏 GitHub Release 的 `target_commitish` 引用。

### 7.3 本地分支与远端对齐

#### 7.3.1 分叉检测

```powershell
git fetch origin master
git log --oneline master..origin/master   # 远端有本地没有的
git log --oneline origin/master..master   # 本地有远端没有的
```

#### 7.3.2 对齐方案选择(按优先级)

| 情况 | 推荐做法 | 禁用做法 |
|---|---|---|
| 远端多出 1 个 commit(merge PR) | `git reset --hard origin/master` | 改用 merge 引入新 merge commit |
| 本地多出 N 个 commit(未推送) | `git push origin master` | `git pull --no-rebase` 然后 push |
| 双向都有(实质冲突) | ❌ **不要自动解决**,人工 review | `git push --force` |

> 关键原则:远端若已经 merge 了 PR,**以远端为准**最简单(release tag 指向该 commit)。

### 7.4 release source of truth:tag

**强制规则**:

1. GitHub Release 的 `target_commitish` 必须是 **commit SHA**,不是分支名
2. 本地 `master` 推进时,**已发布的 tag 不能随之漂移**(tag 是 immutable 的)
3. 发布新版本时,即使 master 已经超过旧 tag,Release 仍然指向原 tag 的 commit

```powershell
# 校验:发布 v2.0.7 后,master 推进到 v2.0.8 期间,v2.0.7 的 release 不变
git rev-parse v2.0.7^{commit}
curl -s -H "Authorization: token $GH_TOKEN" \
  https://api.github.com/repos/colbertlee/langChain_langGraph/releases/tags/v2.0.7 \
  | python -c "import sys,json; d=json.load(sys.stdin); print('release target:', d['target_commitish'][:8])"
# 两次 SHA 必须一致
```

### 7.5 Branch protection rules(分支保护)

#### 7.5.1 必须保护的分支

| 分支 | 重要性 | 保护级别 |
|---|---|---|
| `master` | 生产主线 | 严格(见下) |
| `release/vX.Y.Z*` | 当前 release | 标准 |

#### 7.5.2 master 保护规则

通过 GitHub API 设置(详见 §7.5.4):

```json
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismissal_restrictions": {},
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1,
    "require_last_push_approval": true
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
```

含义:
- ✅ PR 必须经过 1 人 approve
- ✅ 必须 linear history(禁止 merge commit 噪音)
- ✅ 禁止 force push
- ✅ 禁止删除分支
- ❌ 不强制 status checks(本仓库暂未配置 CI;若后续接入 Actions 再启用)

#### 7.5.3 release/* 保护规则

```json
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": null,
  "restrictions": null,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": false,
  "lock_branch": false,
  "allow_fork_syncing": false
}
```

含义:release 分支只读保护,允许 owner 直接 push(因为发布期需要热修)。

#### 7.5.4 一键应用脚本

仓库内提供 3 种调用方式,功能等价,选一种即可:

| 入口 | 平台 | 调用方式 |
|---|---|---|
| [`scripts/release/apply_branch_protection.sh`](../scripts/release/apply_branch_protection.sh) | Linux / macOS / Git Bash | `GH_TOKEN=ghp_xxx ./apply_branch_protection.sh master` |
| [`scripts/release/apply_branch_protection.ps1`](../scripts/release/apply_branch_protection.ps1) | Windows PowerShell | `$env:GH_TOKEN="ghp_xxx"; .\apply_branch_protection.ps1 master` |
| [`scripts/release/release_cli.py`](../scripts/release/release_cli.py) `protect` | 跨平台(集成在统一 CLI 中) | `python scripts/release/release_cli.py protect master --enforce-admins` |

`release_cli.py protect` 子命令会自动按平台选择 `.ps1` 或 `.sh`,并支持 `--enforce-admins=true|false`
二次 patch(用于单 owner 仓库首批 SOP 落地的临时绕过场景)。

下面是底层 `.sh` 实现参考,功能与上述三个入口等价:

```bash
# scripts/release/apply_branch_protection.sh
# 用法:GH_TOKEN=ghp_xxx ./apply_branch_protection.sh

REPO=colbertlee/langChain_langGraph
BRANCH=$1   # master 或 release/v2.0.7-cleanup-verified

case "$BRANCH" in
  master) PAYLOAD='{"enforce_admins":true,"required_pull_request_reviews":{"required_approving_review_count":1,"dismiss_stale_reviews":true},"required_linear_history":true,"allow_force_pushes":false,"allow_deletions":false,"required_conversation_resolution":true}' ;;
  release/*) PAYLOAD='{"enforce_admins":false,"required_pull_request_reviews":null,"required_linear_history":false,"allow_force_pushes":false,"allow_deletions":false}' ;;
  *) echo "unsupported branch: $BRANCH"; exit 1 ;;
esac

curl -s -X PUT \
  -H "Authorization: token $GH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$REPO/branches/$BRANCH/protection" \
  -d "$PAYLOAD" | python -m json.tool
```

> 脚本需要 PAT 含 `repo` scope。
> 首次为 release 分支添加保护前,先确认 release 分支已 merge 进 master(否则锁住后无法修复)。

### 7.6 新增:Orphan Branch Cleanup SOP

> **本节为 v2.0.7 发布后新增的强制性 SOP**。所有 release 完成后必须执行。

#### 7.6.1 为什么需要

GitHub 仓库初始化时会自动创建一个默认分支(2020 年 10 月后为 `main`,
之前为 `master`)。如果本地默认分支是 `master`,push 之后 GitHub 上会同时存在:

- `main`(空,GitHub 自动创建)
- `master`(本地推送的,真实代码)

此外,merge 后的 PR 头分支(例如 `release/v2.0.7-cleanup-verified`)会在 GitHub 上
保留一个 ref,即使 PR 已合并。如果不清理,几个月后仓库会出现大量无人 review 的
僵尸分支。

#### 7.6.2 发布完成后 30 分钟内执行清单

```powershell
# Step 1:确认 orphan 默认分支存在性
git ls-remote origin 'refs/heads/main' 'refs/heads/master'
# 期望:main 不存在(若存在 → orphan),master 必须存在

# Step 2:如果 main 存在且是默认分支 → 必须先切换默认分支才能删除
$payload = @{ default_branch = "master" } | ConvertTo-Json -Compress
$payload | Set-Content -Path $env:TEMP\gh_default_branch.json -Encoding UTF8 -NoNewline
curl -s -X PATCH -H "Authorization: token $env:GH_TOKEN" -H "Content-Type: application/json" `
  --data-binary "@$env:TEMP\gh_default_branch.json" `
  https://api.github.com/repos/colbertlee/langChain_langGraph -w "HTTP %{http_code}\n"

# Step 3:删除 orphan main
curl -s -X DELETE -H "Authorization: token $env:GH_TOKEN" `
  https://api.github.com/repos/colbertlee/langChain_langGraph/git/refs/heads/main `
  -w "HTTP %{http_code}\n"
# 期望:204 No Content
```

#### 7.6.3 release 分支处理

PR merge 完成后,head 分支(例如 `release/v2.0.7-cleanup-verified`)的处理选择:

| 场景 | 做法 |
|---|---|
| 一次性 milestone release(cleanup-verified 等) | 保留 2 周用于 audit,然后删 |
| 长期支持的 release 分支(后续 hotfix 用) | 转 protected branch(见 §7.5.3) |
| 测试中发现的 stale 分支 | 立即删除 |

```powershell
# 保留 audit 窗口(2 周)后,执行:
git push origin --delete release/vX.Y.Z-cleanup-verified

# 本地同步
git remote set-head origin -d
git fetch --prune origin
```

#### 7.6.4 自动化校验(发布 PR 模板自检)

在 `.github/PULL_REQUEST_TEMPLATE/release.md` 加入:

```markdown
## 发布后自检(必填)

- [ ] 孤儿 `main` 分支已删除
- [ ] `default_branch` 已设为 `master`
- [ ] `release/vX.Y.Z*` 分支已决定保留 / 删除
- [ ] CHANGELOG.md 已更新本版本条目
- [ ] 本地 backup 分支(如 `chore/xxx-backup`)已删除
```

#### 7.6.5 与 §7.1 的关系

- §7.1 是**通用** orphan 分支清理规则(适用于所有阶段)
- §7.6 是**发布后**强制的清理清单(§7.1 的发布特化版)
- 两者**不可替代**:即使你按 §7.1 删除了所有 orphan,如果跳过了 §7.6
  的"切换默认分支"步骤,你会无法删除 orphan `main`(`422 Cannot delete the default branch`)

---

## 8. 常见问题

### Q1. v2.0.7 release 时 GitHub 为什么同时有 `main` 和 `master`?

详见 §7.6。这是 GitHub 仓库初始化默认分支策略导致的,v2.0.7 是第一次遇到,
已在本 SOP 中固化处理流程。

### Q2. tag 和 release 哪个优先?

**tag 优先**。release 是 tag 的可视化展示,GitHub 内部以 tag 为锚点。
**禁止**直接通过 release UI 编辑 `target_commitish` 来"重定向" tag。

### Q3. 发布失败可以回滚 tag 吗?

可以删除本地 + 远端 tag,但 GitHub Release **不可删除**(只能 mark as draft)。
正确的"回滚"姿势:

1. 标记 Release 为 draft
2. 删除 tag
3. 修复后重新打 tag 并发布新的 release,带说明文字"supersedes <old tag>"

### Q4. 本地 backup 分支(`chore/xxx-backup`)何时删?

**发布成功 2 周后**。如果在 2 周内发现发布问题,backup 分支是最快的回滚锚点。

### Q5. `release/vX.Y.Z*` 分支 merge 后 GitHub 还会保留多久?

永久保留,直到你显式 `git push origin --delete` 或在 GitHub UI 关闭 PR 的
"Kepp this branch" 复选框。建议按 §7.6.3 处理。

---

## 附录 A:常用命令速查

```powershell
# 完整 release 流程(从 clean working tree 开始)
git fetch origin master
git rebase origin/master                       # 若分叉
git tag -a vX.Y.Z -m "release: vX.Y.Z"
git push origin master vX.Y.Z

# 关键:发布后必须执行(§7.6)
gh api -X PATCH repos/colbertlee/langChain_langGraph -f default_branch=master
git push origin --delete main                  # 现在才允许

# 验证
gh release view vX.Y.Z --json tagName,targetCommitish
```

## 附录 B:文档历史

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-09-03 | v2.0.7 | 首次发布本文件(此前 commit message 提及但文件未创建);新增 §7.5 分支保护、§7.6 orphan cleanup SOP |
