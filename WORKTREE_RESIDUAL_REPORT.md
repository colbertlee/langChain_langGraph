# Worktree 残留清单（v2.0.10 commit 后）

> 生成时间：2026-09-07
> 生成原因：v2.0.10 cleanup session 内提交了 4 个 commit，期间未触碰 worktree 中已存在的实验性 dirty 改动。本报告供下次清理参考。

---

## 总览

| 类别 | 数量 | 净行数（参考） |
|---|---|---|
| `M` tracked（实验改动，已在工作树但未提交） | 42 | +2110 / -11349（其中含 web_console ~50 个文件大量未读改动） |
| `??` untracked（新文件，未跟踪） | 33 | （大小未统计） |
| **总计** | **75** | |

---

## A. `M` tracked — 待处理（42 个）

### A1. `ai_agent/` —— 改动较大，可能是独立 feature 分支未完成

| 文件 | diff 大小 | 建议 |
|---|---|---|
| `ai_agent/rag.py` | +618 / 改动大 | 🔶 待审查。可能与 `ai_agent/tests/test_tools.py` (-214 行删除) 配套。**建议单独立 commit "refactor(rag)"**。 |
| `ai_agent/tools.py` | -667 | 🔶 待审查。可能与 `rag.py` 配套（同上）。 |
| `ai_agent/app.py` | +157 | 🔶 待审查。可能是新加 endpoint 或 `_seed_demo_workers_into` 改动扩展。 |
| `ai_agent/llm_reliability.py` | +4 | 🟢 微小改动，单行 commit 即可。 |
| `ai_agent/skills.py` | +26 | 🟢 中等改动。 |
| `ai_agent/tests/test_akshare_respx.py` | +28 | 🟢 与 rag 改动可能相关。 |
| `ai_agent/tests/test_rag.py` | +15 | 🟢 与 rag 改动配套。 |
| `ai_agent/tests/test_skills.py` | +22 | 🟢 与 skills.py 配套。 |
| `ai_agent/tests/test_tools.py` | -214 | 🔶 大量删除。可能与 `tools.py` 配套。 |
| `ai_agent/prompts/user_prompts.json` | +2 | 🟢 JSON 微调。 |
| `ai_agent/requirements.txt` | +3 | 🟢 依赖新增。 |
| `ai_agent/CHANGELOG.md` | +2 | 🟢 CHANGELOG 微调。 |

**建议**：先 `git diff HEAD -- ai_agent/rag.py | head -50` 看主题。如果是"RAG 工具迁移"或"RAG v2 适配"主题，单独 commit。

### A2. `web_console/` —— 改动覆盖整个前端，是另一个未完成功能分支

| 类别 | 文件 | 建议 |
|---|---|---|
| 路由 | `App.tsx` / `pages/v2/AdminPage.tsx` / `pages/v2/ChatPage.tsx` | 🔴 路由相关改动；与 v2.0.10 Playwright spec 通过的事实（9 passed）矛盾 → 可能 spec 已更新但实际 UI 跑的是另一分支 |
| 页面 | `pages/{Agents,Approval,Memory,Observability,Prompts,Settings,Tools}.tsx` | 🔴 7 个页面有改动，每个 +20~+400 行 |
| 组件 | `components/assistant-ui/{markdown-text,thread,tool-fallback}.tsx` | 🔴 assistant-ui 适配层有改动 |
| 组件 v2 | `components/v2/{ErrorRateWidget,TokenUsageWidget,ToolCallTimeline,TraceListTable}.tsx` | 🔴 v2 组件小调整 |
| 布局 | `components/layout/{Sidebar,TopBar}.tsx` / `main.tsx` | 🔴 布局改动（含 Sidebar 6→8 入口） |
| Hooks | `hooks/useAgentThreadListRuntime.ts` (-366 行大改) | 🔴 与删 SessionList 相关；可能 hook 已重写 |
| Lib | `lib/api.ts` (+106 行) | 🔴 API client 改动 |
| Stores | `stores/{chatStore,uiStore}.ts` | 🔴 状态管理改动 |
| 样式 | `styles/globals.css` (+146 行) | 🔴 大量 CSS 新增 |
| 配置 | `package.json` / `package-lock.json` / `tsconfig.json` / `vite.config.ts` | 🟡 依赖/配置变更 |
| **总计** | **29 个文件** | 🔴 **强烈建议整批合并为 1 个 commit："feat(web_console): [TBD feature name]"** |

**重要警告**：这些 web_console 改动与 v2.0.10 cleanup 的事实是冲突的：
- v2.0.10 Playwright spec 假设 sidebar 8 入口 → web_console/Sidebar.tsx 当前 dirty 状态可能已实现 8 入口
- v2.0.10 Playwright spec 假设 `/admin?tab=xxx` 路由 → web_console/App.tsx 当前 dirty 状态可能已实现

→ 强烈怀疑 **web_console dirty 改动是 v2.0.10 spec 修复的实际来源**。我清理 session 里改的 `e2e/app.spec.ts` 是基于"UI 已实现但 spec 过期"的判断；UI 的实际实现代码就在这些 dirty 改动里。

**操作建议**：
```bash
# 单批提交所有 web_console dirty 改动：
git add web_console/
git commit -m "feat(web_console): [主题待定]

建议先 git diff --stat 看一下主题。如确实是 v2.0 slim 前端配套，可
考虑作为 v2.0.10 的伴随 commit 在 release tag 前补进来。"
```

---

## B. `??` untracked —— 待 review（33 个）

### B1. 一次性调试产物（建议 discard）

| 路径 | 性质 | 建议 |
|---|---|---|
| `ai_agent/check_models.py` | 单文件调试脚本 | ❌ discard |
| `ai_agent/llm_minimax.py` | MiniMax 实验脚本 | ❌ discard（或拆出独立 commit） |
| `ai_agent/test_request.json` | 调试请求体 | ❌ discard |
| `ai_agent/temperature_chart.html` | matplotlib 渲染产物 | ❌ discard |
| `ai_agent/restart-app.{sh,ps1}` / `stop-app.{sh,ps1}` | 重启脚本（与 `package/windows/*.bat` 配套） | 🔶 可能有用，看是否与 `scripts/` 下现有脚本重复 |
| `ai_agent/package/windows/restart-app.bat` / `stop-app.bat` | 同上 | 🔶 同上 |
| `web_console/src/components/chat/ModelChip.tsx` | README §2.4 引用过，看是否真实使用 | 🔶 可能是被引用但未实现的组件 |
| `web_console/src/components/layout/ThemeSync.tsx` | Theme sync 组件 | 🔶 看是否真实使用 |
| `web_console/src/hooks/useAgentLocalRuntime.ts` | assistant-ui 适配 hook | 🔶 与 `useAgentThreadListRuntime` 是否重复 |
| `web_console/src/lib/chatHistoryAdapter.ts` | Chat 历史 adapter | 🔶 看是否真实使用 |

### B2. Eval 数据集与运行结果（建议评估后 commit 或 discard）

| 路径 | 性质 | 建议 |
|---|---|---|
| `ai_agent/evals/cache_smoke.py` | 缓存冒烟脚本 | 🔶 与 `real_api_smoke.py` 同主题，可合并 |
| `ai_agent/evals/embedding_compare.py` | Embedding 模型对比脚本 | 🔶 可能进 eval infra |
| `ai_agent/evals/rag_eval.py` | RAG 评估脚本 | 🔶 与 `harness.py` 关联 |
| `ai_agent/evals/rag_eval_set.jsonl` | RAG 评估数据集 v1 | 🔶 |
| `ai_agent/evals/rag_eval_set_v2.jsonl` | RAG 评估数据集 v2 | 🔶 |
| `ai_agent/evals/rag_eval_set_v3.jsonl` | RAG 评估数据集 v3 | 🔶 |
| `ai_agent/evals/runs/20260907_182338_real_smoke/` | `real_api_smoke.py` 的 artifact（v2.0.10 引入） | 🟡 已经在 `evals/runs/` 下，**保留**（但应在 `.gitignore` 里） |
| `ai_agent/evals/runs/20260907_182601_real_smoke/` | 同上 | 🟡 同上 |
| `ai_agent/evals/runs/rag_compare_qwen/` | RAG 对比 run artifact | 🔶 与 `rag_eval.py` 配套，建议保留 |
| `ai_agent/evals/runs/rag_compare_qwen_real/` | 同上 | 🔶 |
| `ai_agent/evals/runs/rag_compare_v2/` | 同上 | 🔶 |
| `ai_agent/evals/runs/rag_sweep_v2/` | RAG sweep artifact | 🔶 |
| `ai_agent/evals/runs/rag_sweep_v3/` | 同上 | 🔶 |

### B3. Knowledge base 文档（建议 review 是否纳入 git）

| 路径 | 性质 | 建议 |
|---|---|---|
| `ai_agent/knowledge_base/cooking_basics.txt` | 烹饪知识 | 🔶 |
| `ai_agent/knowledge_base/fitness.txt` | 健身知识 | 🔶 |
| `ai_agent/knowledge_base/gardening.txt` | 园艺知识 | 🔶 |
| `ai_agent/knowledge_base/java_intro.txt` | Java 入门 | 🔶 |
| `ai_agent/knowledge_base/javascript_intro.txt` | JS 入门 | 🔶 |
| `ai_agent/knowledge_base/photography.txt` | 摄影知识 | 🔶 |
| `ai_agent/knowledge_base/travel_guide.txt` | 旅游指南 | 🔶 |

→ 这些看起来是 RAG 的内置文档，**可能被 RAG 系统读取**。如果这样就应该 `git add`，否则建议加 `.gitignore` 忽略 `knowledge_base/*.txt`。

---

## C. 已完成 v2.0.10 commit 总览

```
e18efd9 refactor(agent): remove LEGACY imports + add placeholder key detection
495594e docs+specs: v2.0.10 release notes, CHANGELOG entry, e2e assertion fixes
0230f00 refactor(v2_slim)!: remove LEGACY_MODE switch (BREAKING)
5dd2f29 chore: remove dead code (debug scripts + frontend orphans)
```

---

## D. 下次清理建议（按价值/风险排序）

1. **🔴 高优先**：审查并提交 `web_console/` 29 个 dirty 改动（1 个 commit）。可能是 v2.0.10 spec 修复的真实代码来源。
2. **🔴 高优先**：审查 `ai_agent/rag.py` + `tools.py` + `app.py` + `tests/test_tools.py`（推测 1 个 RAG 工具迁移主题）。
3. **🟡 中优先**：knowledge_base/*.txt → `git add` 或 `.gitignore`。
4. **🟡 中优先**：evals/ 整套（`cache_smoke.py` / `embedding_compare.py` / `rag_eval.py` / `rag_eval_set*.jsonl` / `runs/`）→ 1 个 commit "feat(evals): RAG evaluation infra"。
5. **🟢 低优先**：单独的 MiniMax adapter / `[timing]` 日志 / ChatOpenAI kwargs 调优 → 各 1 个 commit。
6. **❌ Discard**：`check_models.py` / `test_request.json` / `temperature_chart.html` 等纯调试产物。
