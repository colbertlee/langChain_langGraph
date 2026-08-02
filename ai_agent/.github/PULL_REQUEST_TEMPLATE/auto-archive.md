<!-- .github/PULL_REQUEST_TEMPLATE/auto-archive.md -->

## 🚨 Maintainer Review Required

> 本 PR 由 **release-build workflow** 的 `archive-acceptance` job 自动生成。
> **不会自动 merge**。必须由 `@<your-org>/maintainers` team review 后再合并。
>
> 详见：[docs/auto-archive-approval.md](../../docs/auto-archive-approval.md)

> ⚠️ **PR title 强制格式**（Day 23）：
> ```
> auto-archive(<tag>)?: <clean|restore|backfill|migrate|prune|cleanup> <description>
> ```
> 例：`auto-archive: clean 3 errored files`
> 例：`auto-archive(v1.2.3): backfill archive`
>
> CI 校验脚本：`tools/check_pr_title.py`。不匹配 → CI 红 → branch protection 阻止 merge。

## Summary

<!-- 由 release-build 自动填充，**不要手动改这里** -->

{{SUMMARY}}

## 涉及文件

<!-- 由 release-build 自动列出：自动移到 tests-archive/_obsolete/<ts>/ 的文件清单 -->

| 文件 | 大小 | 原路径 | 新路径 |
|------|------|--------|--------|
{{FILES_TABLE}}

## 触发条件

- [ ] Acceptance summary 跑出 `status == "error"`
- [ ] 文件已被移动到 `tests-archive/_obsolete/<TS>/`
- [ ] 主分支 `archive-acceptance` job 全部通过

## Checklist（maintainer 必填）

> ⚠️ **Day 22 enforce**：以下 4 项缺一不可。
> `tools/check_pr_metadata.py` 会在 CI 中校验。
> 若缺任何一项，CI 失败，merge 被 branch protection 阻止。
>
> 详见：[docs/pr-template-required-fields.md](../../docs/pr-template-required-fields.md)

- [ ] 这些文件**确实**应该清理（已无法运行 / 不再维护） ✅ **必填**
- [ ] 没有误杀正在维护的测试 ✅ **必填**
- [ ] 旧文件的 git history 仍然可用（`git log --follow tests-archive/_obsolete/<TS>/<file>`） ✅ **必填**
- [ ] 如果要恢复：`git mv tests-archive/_obsolete/<TS>/<file> tests-archive/tests/` ✅ **必填**

## 风险评估

| 维度 | 评估 |
|------|------|
| 影响范围 | `tests-archive/tests/` 内的 errored 文件（不影响主测试集） |
| 恢复难度 | 低（git mv + commit） |
| 关联 PR / Issue | {{LINKED_ISSUES}} |

## 如何验证

```bash
# 1. 看本地 diff
git diff main -- tests-archive/

# 2. 重新跑 acceptance 确认移除后无新 error
python tools/archive_acceptance.py --strict

# 3. 如果想恢复某文件
git mv tests-archive/_obsolete/<TS>/<file>.py tests-archive/tests/
git commit -m "restore <file> from auto-archive"
```

---

🤖 由 [release-build.yml](../../.github/workflows/release-build.yml) 自动生成 · 触发于 tag `{{TAG_NAME}}`