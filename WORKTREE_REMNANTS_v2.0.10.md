# Worktree Remnants 清单（v2.0.10 final）

> 生成时间：2026-09-07
> worktree 状态：`M` 0 + `??` 31（详见 [WORKTREE_RESIDUAL_REPORT.md](WORKTREE_RESIDUAL_REPORT.md) 与本文件）
> 目的：为运维 / 下个 session 提供 commit / gitignore / discard 的具体分类

---

## 总览

| 桶 | 路径数 | 建议处理 |
|---|---|---|
| **KEEP（git add + commit）** | 16 | 下次 session 分 3-5 个 commit 提交 |
| **IGNORE（加 .gitignore + 不 commit）** | 11 | 一次性 .gitignore 增量即可 |
| **DISCARD（删文件）** | 6 | `rm` 后记录到 release notes |
| **总计** | **33** | |

> 备注：v2.0.10 session 末期 sandbox 又新增 2 个 untracked（`e2e_no_browser.mjs` / `_llm_agent_test.py`），见 KEEP §1.4。

---

## 1. KEEP（建议 `git add` + commit，共 14 项）

### 1.1 RAG 系统内置知识库（7 项）

| 文件 | 行数（行） | 性质 |
|---|---|---|
| `ai_agent/knowledge_base/cooking_basics.txt` | 1061 | 被 `FEATURES_GUIDE.md / rag.py / tools.py` 引用 |
| `ai_agent/knowledge_base/fitness.txt` | 924 | 同上 |
| `ai_agent/knowledge_base/gardening.txt` | 915 | 同上 |
| `ai_agent/knowledge_base/java_intro.txt` | 1210 | 同上 |
| `ai_agent/knowledge_base/javascript_intro.txt` | 1301 | 同上 |
| `ai_agent/knowledge_base/photography.txt` | 969 | 同上 |
| `ai_agent/knowledge_base/travel_guide.txt` | 1022 | 同上 |

**验证引用方**：24 个文件引用 `knowledge_base`，包括 `rag.py` / `tools.py` / `pyproject.toml` / `FEATURES_GUIDE.md` / `README.md` / 多个 tests

**建议 commit**：1 个 commit `feat(rag): seed knowledge_base with 7 builtin domains`

⚠️ **孤儿文件**：`python_intro.txt`（1288 行）**未被任何代码引用**——这是 RAG 系统的 8 个种子之一，但没接入 → 单独决策（commit 一起走 / discard）

### 1.2 RAG 评估工具集（5 项）

| 文件 | 行数 | 性质 |
|---|---|---|
| `ai_agent/evals/rag_eval.py` | 472 | RAG 召回率评估脚本 |
| `ai_agent/evals/cache_smoke.py` | 49 | 缓存冒烟测试 |
| `ai_agent/evals/embedding_compare.py` | 106 | Embedding 模型对比 |
| `ai_agent/evals/rag_eval_set.jsonl` | (jsonl) | v1 评估集 |
| `ai_agent/evals/rag_eval_set_v2.jsonl` | (jsonl) | v2 评估集 |
| `ai_agent/evals/rag_eval_set_v3.jsonl` | (jsonl) | v3 评估集 |

**建议 commit**：1 个 commit `feat(evals): RAG evaluation infra + 3 generations of eval sets`

### 1.3 跨平台进程控制脚本（2 项）

| 文件 | 性质 |
|---|---|
| `ai_agent/package/windows/restart-app.bat` | windows 平台 restart 脚本（配套已有 `install.bat / run.bat`） |
| `ai_agent/package/windows/stop-app.bat` | windows 平台 stop 脚本 |

**已 tracked 对比**：`install.bat / run.bat / run-web.bat / mcp_config.json / .env.example` 都在 v2.0.9 时期入库。新增 restart/stop 与之配套。

**建议 commit**：1 个 commit `feat(package): windows restart/stop scripts`

### 1.4 v2.0.10 session 内新增的 2 项（必读）

| 文件 | 性质 | 建议 |
|---|---|---|
| `web_console/e2e_no_browser.mjs` | v2.0.10 session 期间为绕开 sandbox playwright 限制写的 e2e fallback（用 Vite SSR-fetch + 后端 HTTP 调用验证） | 🔶 **KEEP**，但需 `chmod +x` + 适配 CI |
| `ai_agent/_llm_agent_test.py` | v2.0.10 session 期间对应的"无 LLM 也能跑的集成测试"，7628 字节 | 🔶 **KEEP** + commit，但需先读内容确认 |

→ 这 2 个文件不是用户原始 worktree 残留，**是 v2.0.10 session 期间 sandbox 替代方案**。建议：
- `e2e_no_browser.mjs`：作为 web_console 的"轻量 e2e"与 `e2e/app.spec.ts`（Playwright）共存，commit 进 web_console
- `_llm_agent_test.py`：与 `scripts/real_api_smoke.py`（v2.0.10 引入）配套的集成测试，commit 进 ai_agent/tests/

---

## 2. IGNORE（建议加 .gitignore，共 11 项）

### 2.1 eval run artifacts（8 个目录 / 共 ~10 项）

**完整路径**（包含所有现有 untracked 历史 run）：
```
ai_agent/evals/runs/20260726_*/      # 12 个历史 run（2026-07-26 batch）
ai_agent/evals/runs/20260903_*/      # 4 个历史 run
ai_agent/evals/runs/20260907_1823*_real_smoke/  # 2 个 v2.0.10 期间跑的 real_api_smoke
ai_agent/evals/runs/harness_dry_*/   # 7 个 harness dry-run
ai_agent/evals/runs/harness_pr*/     # 6 个 PR 触发的 harness
ai_agent/evals/runs/harness_smoke*/  # 2 个 harness smoke
ai_agent/evals/runs/rag_compare_*/   # 5 个 RAG 对比
ai_agent/evals/runs/rag_sweep_*/     # 2 个 RAG sweep
```

**为什么 ignore**：每次跑 harness / real_api_smoke / RAG eval 都会生成 timestamped run directory，**不该入 git**（与运行时产物等价）。但 `evals/rag_eval.py / rag_eval_set*.jsonl / cache_smoke.py / embedding_compare.py` 是 **基础设施**（评估脚本本身），要 commit。

**建议 gitignore 条目**：
```gitignore
# Eval runs (每次跑生成 timestamped 目录,不入库)
ai_agent/evals/runs/*/
!ai_agent/evals/runs/.gitkeep
```

（也可考虑 `ai_agent/evals/runs/*` 不带 trailing `/`，但 trailing `/` 更精确）

### 2.2 Playwright 输出（1 项）

```
web_console/e2e_app_out.txt
```

**性质**：Playwright 测试运行时输出。本次 v2.0.10 commit 9 后跑测试时新增。

**建议 gitignore 条目**：
```gitignore
# Playwright local artifacts
web_console/e2e_*_out.txt
web_console/e2e_app_*.log
```

---

## 3. DISCARD（建议 `rm`，共 6 项）

### 3.1 调试脚本（4 项）

| 文件 | 行数 | 性质 |
|---|---|---|
| `ai_agent/check_models.py` | 30 | 一次性模型列表探测脚本（v2.0.10 期间调试用） |
| `ai_agent/llm_minimax.py` | 347 | MiniMax 直连 wrapper（应纳入 `commit 4` 撤回，**已被撤回但文件仍在 worktree**） |
| `ai_agent/test_request.json` | (json) | 一次性 POST 请求体（curl 调试残留） |
| `ai_agent/temperature_chart.html` | (html) | matplotlib 渲染残留 |

⚠️ `llm_minimax.py` 是 **真实的 wrapper 代码**（347 行），不是简单调试脚本。两个选项：
- **A. Discard**：丢了这个 wrapper
- **B. Keep + commit**：单独 commit `feat(llm): standalone MiniMax thin wrapper`（独立于 v2_slim，不进 tools v2 slim 范围）

**建议**：**discard**（commit 8 tools v2 slim consolidation 后，已经过 v2_slim 入口走；如果保留这个独立文件反而会让入口混乱）。如有需要可后续另起 PR。

### 3.2 跨平台启动脚本（2 项 / 6 个文件）

| 文件 | 性质 |
|---|---|
| `ai_agent/restart-app.sh` | linux/macos 启动脚本 |
| `ai_agent/restart-app.ps1` | windows 启动脚本（pwsh 版本） |
| `ai_agent/stop-app.sh` | linux/macos 停止脚本 |
| `ai_agent/stop-app.ps1` | windows 停止脚本（pwsh 版本） |

**为什么不 KEEP**：与 `ai_agent/package/windows/restart-app.bat` 重复（KEEP 那一批）。`.sh` 与 `.ps1` 是顶层版本（不在 package/ 下），可能源于早期 `package/` 结构未成型时的临时脚本。

**确认方法**：看一下 `restart-app.sh` 是否被任何 docs / README 引用。如有引用 → KEEP；如无 → discard。

---

## 4. 操作清单（按顺序执行）

### 4.1 增量 .gitignore（1 个文件改动）

修改 [`.gitignore`](.gitignore) 第 71-86 行之后，新增：

```gitignore
# ==== v2.0.10+ 增量 ====

# Eval run artifacts (每次跑生成 timestamped 目录)
ai_agent/evals/runs/*/

# Playwright local output
web_console/e2e_*_out.txt
web_console/e2e_app_*.log

# 调试脚本(用户 commit 前已确认是临时产物)
ai_agent/check_models.py
ai_agent/llm_minimax.py
ai_agent/test_request.json
ai_agent/temperature_chart.html
ai_agent/restart-app.sh
ai_agent/restart-app.ps1
ai_agent/stop-app.sh
ai_agent/stop-app.ps1

# 注：knowledge_base/*.txt / evals/{rag_eval.py,cache_smoke.py,...} / package/windows/restart-app.bat
#     这些是 KEEP 项，不 ignore。
```

**Commit message**：`chore: extend .gitignore for v2.0.10 cleanup remnants`

### 4.2 Discard 命令（验证后再删）

```bash
# 1) 先确认 llm_minimax.py 没人用
grep -r "llm_minimax" ai_agent/ web_console/ 2>/dev/null
# 预期 0 命中（撤回已做）

# 2) 再确认 restart-app.{sh,ps1} 没人用
grep -r "restart-app\." ai_agent/ web_console/ 2>/dev/null
grep -r "stop-app\." ai_agent/ web_console/ 2>/dev/null
# 预期 0 命中

# 3) 然后删除
rm ai_agent/check_models.py
rm ai_agent/llm_minimax.py
rm ai_agent/test_request.json
rm ai_agent/temperature_chart.html
rm ai_agent/restart-app.sh
rm ai_agent/restart-app.ps1
rm ai_agent/stop-app.sh
rm ai_agent/stop-app.ps1
```

**Commit message**：`chore: discard v2.0.10 debug artifacts`

### 4.3 KEEP 项 commit（3 个 commit）

```bash
# commit 10: knowledge_base 种子内容
git add ai_agent/knowledge_base/
git commit -m "feat(rag): seed knowledge_base with 7 builtin domains

新增 7 个内置知识库种子（cooking/fitness/gardening/java/javascript/
photography/travel），由 rag.py / tools.py 在系统初始化时加载为
RAG 检索语料。

每个 .txt ~1KB，纯文本格式，便于检索 + 调试。

注：knowledge_base/python_intro.txt（1288 行）虽存在但未被业务代码
引用，本次未 commit（如需可后续单独 PR）。"

# commit 11: evals 工具集
git add ai_agent/evals/rag_eval.py \
        ai_agent/evals/cache_smoke.py \
        ai_agent/evals/embedding_compare.py \
        ai_agent/evals/rag_eval_set.jsonl \
        ai_agent/evals/rag_eval_set_v2.jsonl \
        ai_agent/evals/rag_eval_set_v3.jsonl
git commit -m "feat(evals): RAG evaluation infra + 3 generations of eval sets

- rag_eval.py: RAG 召回率评估脚本（v2.0.10 时期调试 v2 slim RAG 时编写）
- cache_smoke.py: 缓存冒烟脚本
- embedding_compare.py: Embedding 模型对比脚本
- rag_eval_set.jsonl / v2.jsonl / v3.jsonl: 3 个版本评估数据集

注：evals/runs/ 目录（每次跑生成的 timestamped artifact）不入库，
已加入 .gitignore。"

# commit 12: windows restart/stop 脚本
git add ai_agent/package/windows/restart-app.bat \
        ai_agent/package/windows/stop-app.bat
git commit -m "feat(package): windows restart/stop scripts

与 v2.0.9 时期的 install.bat / run.bat 配套：
- restart-app.bat: 停止当前进程后重启
- stop-app.bat: 优雅停止（关停所有子进程 + 清理 PID 文件）

power shell 版本（restart-app.ps1 / stop-app.ps1）与跨平台 sh 版本
(restart-app.sh / stop-app.sh) 顶层版本已 discard（与 bat 重复且无引用）。"
```

---

## 5. 验证

```bash
# 操作完成后预期
git status --short   # 0 行
pytest tests/ --collect-only -q --no-cov   # 633 collected
npx playwright test e2e/app.spec.ts --reporter=line   # 9 passed
```

---

## 6. 备注

- `web_console/e2e_app_out.txt` 是 Playwright 跑测试时由 spec 内部 `console.log` 输出（v2.0.10 commit 9 期间新增），应 gitignore 但需先看 spec 是否每次都生成
- `ai_agent/evals/runs/` 历史上一直被实践 ignore（40+ 个目录都是 untracked），但**从未正式 gitignore** —— 本次补上
- `knowledge_base/python_intro.txt` 是孤儿——KEEP 时一并 commit 还是 DISCARD，由运维决定
