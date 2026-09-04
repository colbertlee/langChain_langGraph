<!--
  Release PR Template · v2.0.7+

  Usage: open PR at
    https://github.com/colbertlee/langChain_langGraph/compare/master...<branch>?template=release.md

  Ref: docs/VERSION_MANAGEMENT.md (especially section 7 - Post-release cleanup)
-->

# Release PR · vX.Y.Z

> 填写这个模板之前,请先阅读 [docs/VERSION_MANAGEMENT.md](docs/VERSION_MANAGEMENT.md) §7.6。

## 1. 版本信息

| 项 | 值 |
|---|---|
| 版本号 | `vX.Y.Z` |
| SemVer 类型 | [ ] MAJOR (breaking) / [ ] MINOR (feature) / [ ] PATCH (fix/cleanup) |
| 上一版本 | `vX.Y.(Z-1)` |
| Release 分支 | `release/vX.Y.Z[-suffix]` (可选) |
| `pyproject.toml` version | `X.Y.Z` |
| `CHANGELOG.md` 已更新 | [ ] ✅ |

## 2. 改动摘要

<!-- 一句话总结这次发布做了什么 -->

## 3. 验证 (必填 · 对齐 docs/POST_CLEANUP_VERIFICATION.md 四层检查)

| 层 | 检查 | 结果 |
|---|---|---|
| L1 静态 | `ruff check .` / `mypy ai_agent` / `vite build` | [ ] Pass |
| L2 单测 | `pytest ai_agent/tests -q` | [ ] Pass · X/Y |
| L2 前端 | `pnpm vitest run` | [ ] Pass · X/Y |
| L3 Agent 烟雾 | `evals.runner run --all` | [ ] Pass · X/Y |
| L4 运行时 | cold start / hooks / memory | [ ] 记录秒数 + RSS |

## 4. 二进制产物 (如有)

| 平台 | 产物仓库 | 资产文件名 |
|---|---|---|
| Windows | `colbertlee/ai-agent-releases` (Gitee 镜像) | `AI-Agent-X.Y.Z-windows.zip` |
| Linux | 同上 | `AI-Agent-X.Y.Z-linux.tar.gz` |
| macOS | 同上 | `AI-Agent-X.Y.Z-macos.dmg` |
| Wheel | PyPI / Gitee packages | `ai_agent-X.Y.Z-py3-none-any.whl` |

## 5. 发布后自检清单 (必填 · 对应 VERSION_MANAGEMENT.md §7.6.4)

> **这一节是合并前必须勾完的**,否则可能造成 `main` / `master` 长期残留。

- [ ] **§7.6.2 步骤 1**:确认 orphan `main` 不存在或已删除
  ```bash
  git ls-remote origin 'refs/heads/main'   # 应为空
  ```
- [ ] **§7.6.2 步骤 2**:`default_branch` 已设为 `master`
  ```bash
  curl -s -H "Authorization: token $GH_TOKEN" \
    https://api.github.com/repos/colbertlee/langChain_langGraph \
    | grep default_branch   # 应为 master
  ```
- [ ] **§7.6.3**:`release/vX.Y.Z*` 分支已决定保留 / 删除(默认保留 2 周 audit)
- [ ] **§7.4**:Release 的 `target_commitish` 必须是 commit SHA,不是分支名
- [ ] 本地 backup 分支(如 `chore/xxx-backup`)已删除
- [ ] 本地 tag 与远端 tag 一致(`git fetch --tags origin` 不再报 clobber)
- [ ] Gitee 镜像已同步:
  ```bash
  git push gitee master
  git push gitee vX.Y.Z [vX.Y.Z-cleanup-verified]
  ```

## 6. 自动化命令 (可选,推荐)

如果使用 [scripts/release/release_cli.py](../../scripts/release/release_cli.py):

```bash
# Step 1: 启用分支保护(若 master 是新规则,首次需要)
export GH_TOKEN=ghp_xxx
python scripts/release/release_cli.py protect master --enforce-admins

# Step 2: 发布到 GitHub
python scripts/release/release_cli.py github X.Y.Z \
  --body release_notes/vX.Y.Z.md \
  --asset dist/AI-Agent-X.Y.Z-windows.zip

# Step 3: 同步到 Gitee
python scripts/release/release_cli.py gitee X.Y.Z

# Step 4: 清理(若 main 是 orphan)
python scripts/release/release_cli.py cleanup \
  --switch-default-to-master --delete-main

# Step 5: 验证
python scripts/release/release_cli.py status
```

## 7. 回滚预案

如果发布后发现严重问题:

1. **不删除 tag** — GitHub Release 一旦 published 无法删除,只能 mark as draft
2. **修复后** 重新打 tag `vX.Y.Z-hotfix.1` 并发布新 release,在 body 中说明 "Supersedes vX.Y.Z"
3. **不要** 删除或 force-push 旧 tag,会破坏 `target_commitish` 引用

详见 VERSION_MANAGEMENT.md §8 Q3。

## 8. 关联

<!-- 关联的 issue / discussion / 上一个 release PR -->

- 上一 release PR: #X
- 关联 issue: #X, #Y
- 清理报告: docs/POST_CLEANUP_VERIFICATION.md

---

## Reviewer Checklist (合并前 review 必看)

- [ ] L1-L4 验证都有截图或日志
- [ ] §5 所有 checkbox 已勾完
- [ ] 没有遗漏的 `backup-*` / `*-wip` 分支
- [ ] CHANGELOG.md 的 Migration 段已写(若有 breaking change)
- [ ] 二进制产物如果变化,DISTRIBUTION.md 同步更新
