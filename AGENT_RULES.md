# AGENT_RULES.md · AI 助手在本仓库的行为规则

> **范围**：所有在本仓库 `e:\langChain_langGraph` 内工作的 AI 助手（任何工具）。
>
> **优先级**：与 [`docs/PROMPT-PACK.md` §1.4 / §1.6](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md) 冲突时，**以 PROMPT-PACK 为准**；
> 与 [`CONTRIBUTING.md`](file:///e:/langChain_langGraph/CONTRIBUTING.md) 冲突时，**以本文件 §7 红线为准**；
> 与用户实时指令冲突时，按 §6 升级路径处理（**不允许自行解读**）。

---

## 1. 工作流程（接任务 → 交付）

任何任务的最小执行单元必须按下列顺序串行：

1. **摸底** — `LS` 看目录结构；`Grep` / `SearchCodebase` 定位相关代码；`Read` 必读文件（含 `file:///` 行号记录）。
2. **列计划** — `TodoWrite` 把任务拆成 3+ 步；每步可被独立验证。
3. **最小修改** — 只动当前任务必要的代码与文档；不顺手重构无关代码（依据 [`docs/PROMPT-PACK.md` §1.4 第 6 条](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md)「不要顺手扩大改动范围」）。
4. **自检** — 走 §2 检查顺序；走 §3 输出格式。
5. **落盘** — 修改文件用 `Edit`（已存在）或 `Write`（必须新建时）；引用用 `file:///` 行号链接。
6. **审计** — 把本轮改动追加到 [`output/MEMORY.md`](file:///e:/langChain_langGraph/output/MEMORY.md) 对应会话；如影响跨会话档案，同步更新 [`docs/PROMPT-PACK.md`](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md) §3 / §4 / §5。

---

## 2. 检查顺序（证据 → 推理 → 结论）

每一次回答前，按下列 5 条自检（任一不通过先回去补证据 / 澄清，再作答）：

1. 引用的每一处代码是否都来自实际 `Read`？是否有未读就引用？
2. 每一处结论是否能追溯到具体证据（文件路径+行号 / 文档 / 命令输出）？
3. 是否为了"显得在做事"而编造了内容？
4. 是否改变了用户没要求改变的功能？
5. 不确定的地方是否已显式标注（"假设 / 可能 / 需确认 / 未验证"），而不是含糊带过？

---

## 3. 输出格式（必含要素）

- **代码引用**：统一 `file:///absolute/path` 或 `file:///absolute/path#Lx-Ly`；链接文本用 basename，不加反引号。
- **命令输出引用**：给真实命令名 + 真实 SHA256 / 行号 / 计数；不可用的标"未验证"。
- **结论**：可证事实 / 推断 / 猜测 三者必须区分；后两者显式标注。
- **不确定性**：写限定词，不含糊；信息不足直接说"信息不足，无法回答"，并列出缺失证据。
- **每条结论后挂"证据指针"小节**（在本会话答复末尾即可，跨会话归档写进 MEMORY）。

---

## 4. 工具调用条件与权限边界

### 4.1 默认放行（无需批准）
- `LS` / `Glob` / `Grep` / `SearchCodebase` / `Read`
- `TodoWrite` / `AskUserQuestion` / `Skill`（仅在 Skill 自身可用时）

### 4.2 默认允许但需前置条件（满足任一即可）
- `Edit` / `Write`：目标文件必须先 `Read` 过（已存在文件）/ 或本轮 `TodoWrite` 显式列出新建（不存在文件）。
- `RunCommand`：仅在以下条件之一成立才可执行 ——
  - 命令幂等（连跑两次结果哈希不变），或
  - 用户本轮显式批准，或
  - 已在 `TodoWrite` 列出并被自动放行（如 `Get-FileHash`、`Get-Content` 等只读命令）。

### 4.3 必须显式批准（即便有 TodoWrite）
- `DeleteFile` / `StopCommand`
- `RunCommand` 中任何写动作：`git commit` / `git push` / `git reset --hard` / `git checkout -- .` / `git clean -f` / `git branch -D` / `npm install` / `pip install` / `docker run` 等。
- `force push` 到 `main` / `master`：**始终拒绝并提示用户**，即便用户主动要求也需二次确认。

### 4.4 禁止使用（红线，无需批准也不可执行）
- 把真实凭据（GitHub Token / PyPI / GHCR / API Key / 邮箱密码）写入代码 / 文档 / 日志 / 命令行参数；只能在 `.env` / 用户主目录凭据库。
- `WebFetch` 抓取需要登录的服务（GitHub Enterprise / Feishu / Lark / 内部系统）—— 走专用 MCP 工具。
- 任何"看起来无害但实际不可逆"的批量删除 / 覆盖（必须先 `git status` + `git diff --stat` 自报，再走 §5 备份/回滚）。

### 4.5 网络与外部依赖
- `WebSearch` / `WebFetch`：仅在 [`docs/PROMPT-PACK.md` §1.6 第 2/4 条](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md) 允许的研究场景下使用，且结论必须给 URL；WebFetch 后必须在回复末尾附 "Sources:" 列表。
- 不得安装任何第三方依赖除非确有必要且事先说明理由（沿用 [`docs/PROMPT-PACK.md` §1.4 第 5 条](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md)）。

---

## 5. 变更前的备份 / 验证 / 回滚

### 5.1 备份
- 改动 ≥ 10 行或 ≥ 2 个文件：先 `git diff --stat` 自报影响面。
- 改动 `docs/PROMPT-PACK.md` / `AGENT_RULES.md` / `AGENTS.md` 等关键档案：先 `Get-FileHash -Algorithm SHA256` 取基线，落 `output/MEMORY.md` 留档（避免在档案正文里写死哈希）。

### 5.2 验证
- Python 改动 → `ai-agent-lint` + `ai-agent-test`（[`CONTRIBUTING.md` §3.3](file:///e:/langChain_langGraph/CONTRIBUTING.md)；`ai-agent-lint` / `ai-agent-test` 命令定义见 [ai_agent/pyproject.toml](file:///e:/langChain_langGraph/ai_agent/pyproject.toml) `[project.scripts]`）。
- 前端改动 → `npm run check` + `npm test`（[`CONTRIBUTING.md` §3.3](file:///e:/langChain_langGraph/CONTRIBUTING.md)）。
- 文档改动 → 不需要测试，但 PR 标题写 `docs:`。
- 不可用的工具 / 命令 → 标"未验证"，不冒充已通过。

### 5.3 回滚
- 单文件可逆改动 → `git checkout -- <path>`。
- 多文件 / 跨目录 → `git stash` 或新建回滚 commit。
- 跨分支破坏性回滚 → `git revert <commit>`；绝不 `reset --hard` 除非用户显式要求并二次确认。

---

## 6. 冲突判断与升级路径

### 6.1 优先级（从高到低）
1. 仓库硬性约束（[`docs/PROMPT-PACK.md` §1.4 / §1.6](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md)）
2. 本文件 `AGENT_RULES.md`（含 §7 红线）
3. [`CONTRIBUTING.md`](file:///e:/langChain_langGraph/CONTRIBUTING.md) / [`.github/CODEOWNERS`](file:///e:/langChain_langGraph/.github/CODEOWNERS) / 其他仓库规范
4. 用户实时指令
5. AI 工具默认行为

### 6.2 例外（红线凌驾一切）
当用户实时指令与"禁止伪造 / 幻觉 / 不可逆破坏"三类红线冲突时，**拒绝执行并说明原因**，不静默绕过、不"先做再问"。

### 6.3 升级路径
- 规则之间冲突 → 查 §6.1 优先级；同档冲突 → 取更严格者。
- 规则与用户意图冲突 → 用 `AskUserQuestion` 澄清，**不允许自行解读**。
- 用户实时改写了规则 → 写入 `output/MEMORY.md` 对应会话；下一次重读本文件时以最新正文为准。
- 工具不支持某条规则 → 工具能力差异表见 §8；不可绕过红线。

---

## 7. 禁止事项（红线）

| # | 红线 | 来源 |
|---|---|---|
| R1 | 禁止伪造命令输出、文件内容、哈希、URL、行号 | [`docs/PROMPT-PACK.md` §1.6 第 3/4 条](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md) |
| R2 | 禁止未经 `Read` 就引用代码 / 配置 | [`docs/PROMPT-PACK.md` §1.6 第 2 条](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md) |
| R3 | 禁止顺手重构 / "顺手优化"无关代码 | [`docs/PROMPT-PACK.md` §1.4 第 6 条](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md) |
| R4 | 禁止把真实凭据写入代码 / 文档 / 日志 / 命令行参数 | §4.4 |
| R5 | 禁止 `force push` 到 `main` / `master` | §4.3 |
| R6 | 禁止把具体 AI 工具专有字段名写到 PROMPT-PACK §1–§4 正文（仅附录可出现） | [`docs/PROMPT-PACK.md` §1.4 第 3 条](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md) |
| R7 | 禁止 `git reset --hard` / `git checkout -- .` / `git clean -f` / `git branch -D` 未经显式批准 | §4.3 |
| R8 | 禁止静默"先做再问"——冲突必须 `AskUserQuestion` | §6.3 |

---

## 8. 附录：工具差异适配表

> 本节只列**条目级**适配方法；具体工具专有字段名不出现于本表，正文保持工具无关。

| 工具类型 | 如何让本规则生效 | 备注 |
|---|---|---|
| 支持仓库顶层 `AGENTS.md` | 由 [`AGENTS.md`](file:///e:/langChain_langGraph/AGENTS.md) 链入本文件 | 跨工具通用入口（已实测：AGENTS.md 引用本文件 3 处） |
| 需要代码风格约定（而非行为规则） | 另见 [`CONVENTIONS.md`](file:///e:/langChain_langGraph/CONVENTIONS.md)（从代码实测得出的风格/结构/校验口径，每条带行号证据） | 该文件只管「代码长什么样」；本文件管「AI 怎么干活」，两者不重复 |
| 支持工具专属规则文件（如 `CLAUDE.md` / `.cursor/rules/` 等） | 在该工具专属规则文件首行写一段 "请读 `AGENT_RULES.md`"；具体 include 语法因工具而异，按该工具官方文档填写（**未在本机 GUI 实测**，标推测） | 不复制正文，避免双源漂移 |
| 仅支持单条长 System Prompt | 粘贴本文件 §1、§4、§7 三章 | 体积受限时取舍 |
| 不支持任何规则文件 | 由人工在每次会话首条消息粘贴本文件 §1 + §7 | 最低适配 |

---

## 证据指针（每次回答末尾自检后填写）

- 本规则文件自身：[`AGENT_RULES.md`](file:///e:/langChain_langGraph/AGENT_RULES.md)
- 上游档案：[`docs/PROMPT-PACK.md`](file:///e:/langChain_langGraph/docs/PROMPT-PACK.md)
- 入口指针：[`AGENTS.md`](file:///e:/langChain_langGraph/AGENTS.md)
- 人类规范：[`CONTRIBUTING.md`](file:///e:/langChain_langGraph/CONTRIBUTING.md)
- Reviewer：[`.github/CODEOWNERS`](file:///e:/langChain_langGraph/.github/CODEOWNERS)
