# v2.0.10 Release Runbook

> **⚠️ DO NOT EXECUTE BLINDLY — read every step before running.**
>
> This is a checklist of release operations. Each command is annotated with
> what it does and what side-effects it has. Operator is responsible for
> verifying the worktree state matches [WORKTREE_RESIDUAL_REPORT.md](WORKTREE_RESIDUAL_REPORT.md)
> "next time" plan **BEFORE** tagging.

---

## 0. Pre-flight checklist

```bash
# 0.1 verify worktree is clean (only untracked eval artifacts expected)
git status --short
# 预期输出：仅 ?? ai_agent/evals/runs/* + ?? WORKTREE_RESIDUAL_REPORT.md（这份报告本身）

# 0.2 verify 4 commits are present
git log --oneline -4
# 预期：
#   e18efd9 refactor(agent): remove LEGACY imports + add placeholder key detection
#   495594e docs+specs: v2.0.10 release notes, CHANGELOG entry, e2e assertion fixes
#   0230f00 refactor(v2_slim)!: remove LEGACY_MODE switch (BREAKING)
#   5dd2f29 chore: remove dead code (debug scripts + frontend orphans)

# 0.3 verify pytest + playwright green
cd ai_agent && py -3.11 -m pytest tests/ --no-cov -q 2>&1 | tail -5
cd ../web_console && npx playwright test e2e/app.spec.ts --reporter=line 2>&1 | tail -3

# 0.4 verify network/credentials
gh auth status                    # 必须已登录
echo "$GH_TOKEN" | head -c 8      # 检查 GitHub PAT
# Gitee 镜像如不需要可跳过
```

**如果 0.1-0.4 任何一项不通过，停止发布**。

---

## 1. Push tag + GitHub Release

```bash
cd /path/to/langChain_langGraph

# 1.1 发布到 GitHub（自动：创建 annotated tag → push tag → 创建 Release）
python scripts/release/release_cli.py github 2.0.10 \
  --title "v2.0.10 — Cleanup: LEGACY removal (BREAKING)" \
  --body release_notes/v2.0.10.md
```

**这会执行**：
1. `git tag -a v2.0.10 -m "release: v2.0.10"`
2. `git push origin v2.0.10`
3. 创建 GitHub Release，body 从 `release_notes/v2.0.10.md` 读取

**dry-run 选项**（建议先 dry-run）：
```bash
python scripts/release/release_cli.py github 2.0.10 \
  --body release_notes/v2.0.10.md \
  --skip-push          # 只创建 Release 不 push tag（先看 Release 内容）
# 验证完后再 --skip-push 去掉重跑真发布
```

**回滚（已 push 但发现 release 有问题）**：
```bash
# 删除 GitHub Release
gh release delete v2.0.10 --yes
# 删除本地 + 远程 tag
git tag -d v2.0.10
git push origin --delete v2.0.10
```

---

## 2. Gitee 镜像（可选）

```bash
python scripts/release/release_cli.py gitee 2.0.10 \
  --create-release \
  --body release_notes/v2.0.10.md
```

**这会执行**：
1. push tag 到 Gitee 镜像
2. 通过 Gitee OpenAPI v5 创建 Release

**前置**：需 Gitee access token（CLI 内部调用，需在 `$HOME/.config/release_cli/state.json` 或环境变量）

---

## 3. Post-publish cleanup

按 [docs/VERSION_MANAGEMENT.md §7.6](docs/VERSION_MANAGEMENT.md) 执行：

```bash
# 3.1 确认 tag 已对齐 remote
git fetch origin --tags
git tag -l "v2.0.10*" --format='%(refname:short) %(objecttype) %(objectname:short) %(subject)'

# 3.2 orphan branch cleanup（如有）
python scripts/release/release_cli.py cleanup --list-remote    # 先看
python scripts/release/release_cli.py cleanup \
  --switch-default-to-master \
  --delete-main

# 3.3 确认 master 与 origin 对齐
git rev-parse master
git rev-parse origin/master
# 必须相同
```

---

## 4. Verify

```bash
# 4.1 GitHub Release 公开页可见
gh release view v2.0.10 --repo colbertlee/langChain_langGraph

# 4.2 tag 在 GitHub 可见
gh api repos/colbertlee/langChain_langGraph/tags/v2.0.10

# 4.3 监控脚本能正常 probe
curl https://api.github.com/repos/colbertlee/langChain_langGraph/releases/latest \
  | python -c "import json,sys; r=json.load(sys.stdin); print(r['tag_name'], r['published_at'])"

# 4.4 给 release 打 release / released 标签（触发 PR-merge-label workflow）
python scripts/release/release_cli.py webhook \
  --pr-number <RELEASE_PR_NUMBER> \
  --label release \
  --comment "Released as v2.0.10 🎉"
```

---

## 5. Announce

```markdown
# 草稿（粘贴到 Slack / Teams / 邮件）

🚀 v2.0.10 已发布！

⚠️ BREAKING CHANGE: AIAgent_LEGACY 环境变量从 v2.0.10 起完全无效。
   部署中如有设置，请移除（详见 release notes）。

变更亮点：
• 删除 7 个 v2_slim/*_legacy.py + LEGACY_MODE 真回滚分支
• 删除 26 个 tests/legacy + 10 个 scripts/legacy_tests + 47 个调试脚本
• 删除 web_console 死代码 pages/Chat.tsx + SessionList*
• 新增 real_api_smoke.py 真实 LLM provider 冒烟
• 文档：release notes + CHANGELOG + STAGING P2 全部标完成

详情见 release notes: https://github.com/colbertlee/langChain_langGraph/releases/tag/v2.0.10
升级指引：release_notes/v2.0.10.md §Upgrade notes
回滚方案：git revert <v2.0.10-commit-sha>
```

---

## 6. Done

- [x] 4 commits 本地 ready
- [x] release_notes/v2.0.10.md 完整
- [x] CHANGELOG.md 顶部条目完整
- [x] pytest + playwright + vitest 全绿（最终验证见 commit message）
- [ ] Tag pushed to GitHub
- [ ] GitHub Release created
- [ ] Gitee mirrored
- [ ] Post-publish cleanup done
- [ ] Announcement posted
