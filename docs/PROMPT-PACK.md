---
project: langChain_langGraph
doc: PROMPT-PACK
version: 5
generated_at: 2026-10-19T21:00:00+08:00
source_sessions:
  - input/2026-10-13/session-01.md
  - input/2026-10-13/session-02.md
  - input/2026-10-19/session-01.md
  - input/2026-10-19/session-02.md
portable: true
---

# 0. 使用说明（给未来的 AI 助手看）

本文件是 `e:\langChain_langGraph` 项目的交接档案。若你被要求「读这份档案然后继续开发」：
先读第 1 章建立项目上下文，再按第 3 章的约束动手；不确定的地方查第 5 章未决问题，
**不要臆测、不要编造本项目不存在的文件或接口**。档案第 2 章是历次真实提示词原文，不得改写。

若你被要求"继续开发本项目的 agent"：
1. 先读本文件。
2. 再读 [`README.md`](file:///e:/langChain_langGraph/README.md) 与 [`ai_agent/README.md`](file:///e:/langChain_langGraph/ai_agent/README.md)（若存在）。
3. 看 `ai_agent/` 与 `web_console/` 实际目录结构，不要假设未列出的文件存在。
4. 完成任务后，按"提示词 4"重建本档案第 2、3、4、5 章。

# 1. 项目档案

## 1.1 目标与范围（一句话说明 + 边界：做什么、明确不做什么）

**目标**：构建一站式多功能 AI Agent 平台 `langChain_langGraph`。后端基于 LangChain 1.x + LangGraph + MCP（Model Context Protocol），前端为 React 控制台，可经 PyPI / Docker GHCR / Scoop / Homebrew 多渠道分发，支持 Windows / Linux / macOS 桌面二进制。已发布至 v2.5.0（来自 [`README.md`](file:///e:/langChain_langGraph/README.md) 第 3 行）。

**明确不做什么**：
- 不引入新的关系型数据库（沿用 SQLite）。
- 不强制使用 OpenAI（已声明 11 家 LLM Provider、70+ 模型）。
- 不在移动端保证完整功能（README 明确移动端仅查看）。
- 当前阶段不引入多租户/鉴权（见 [.trae/documents/PRD.md](file:///e:/langChain_langGraph/.trae/documents/PRD.md) §2.1）。

## 1.2 技术栈与运行环境（真实版本号，来自真实命令输出）

来自 `README.md`「0. 兼容性矩阵」（未在本机实测命令输出；以下为 README 明文声明）：

| 项 | 支持范围 |
| --- | --- |
| Python | 3.11 / 3.12 / 3.13 |
| Node.js | 20 LTS / 22 LTS |
| 操作系统 | Windows 10/11、macOS 12+、Ubuntu 20.04+/Debian 11+ |
| 浏览器 | Chrome 120+ / Edge 120+ / Safari 17+ / Firefox 122+ |
| Docker | 24+ / docker compose v2 |
| 内存 | ≥ 4 GB（PyInstaller 解压后 ~1.2 GB） |
| 磁盘 | ≥ 3 GB（含 RAG / Chroma 索引） |
| LLM Provider | 11 家 / 70+ 模型 |
| Embedding | OpenAI / 智谱 / MiniMax / Jina |

后端基座（来自 [.trae/documents/TECHNICAL_ARCHITECTURE.md](file:///e:/langChain_langGraph/.trae/documents/TECHNICAL_ARCHITECTURE.md) 与 [README.md](file:///e:/langChain_langGraph/README.md)）：
- 后端：FastAPI（沿用既有 `api.py` / `web_ui.py`）
- Agent：LangChain 1.x + LangGraph + MCP
- 前端：React 19 + TypeScript + Vite 5 + Tailwind 3 + Zustand（持久化 IndexedDB/localStorage）
- 路由：`react-router-dom` 6
- 组件库：`shadcn/ui`（按需复制源码到 `src/components/ui/`）
- Markdown：`react-markdown` + `remark-gfm` + `react-syntax-highlighter`（Prism）
- 流式：`@microsoft/fetch-event-source`（POST SSE）或原生 `fetch` + ReadableStream
- HTTP：`ky`

> **未验证项**：以上版本矩阵为 README/技术架构文档明文；尚未在本机执行 `python --version` / `node --version` 实测。本轮不写"实测结果"以避免伪造。

## 1.3 目录结构与关键文件（只列真实存在的路径）

仓库根目录 `e:\langChain_langGraph`（基于本次 `LS` 的真实结果）：

| 路径 | 角色 | 是否改动 |
| --- | --- | --- |
| [`README.md`](file:///e:/langChain_langGraph/README.md) | 顶层 README，能力矩阵与分发渠道 | 仅引用，不改 |
| `CHANGELOG.md` | 版本变更日志 | 不改 |
| `docs/PROMPT-PACK.md` | 可复用开发档案（本文件） | 本轮新增 |
| `AGENTS.md` | 跨工具入口指针 | 本轮新增 |
| `.trae/documents/PRD.md` | PRD | 仅引用 |
| `.trae/documents/TECHNICAL_ARCHITECTURE.md` | 技术架构 | 仅引用 |
| [`ai_agent/`](file:///e:/langChain_langGraph/ai_agent/README.md) | Python 后端包 | 不在本轮范围 |
| `web_console/` | React SPA | 不在本轮范围 |
| `ai_agent/_ragmoduletest/` | RAG 模块级端到端 harness（含 m1~m8） | 本轮仅引用，不改功能 |
| `ai_agent/knowledge_base/` | 8 个 KB 文本（python / js / java / cooking / travel / photography / fitness / gardening） | 不改 |
| `ai_agent/evals/` | 评测集与历史 sweep 结果 | 不改 |
| `input/` | 会话留痕（用户输入逐字符） | 本轮新建 |
| `output/` | 会话留痕（Agent 产出） | 本轮新建 |
| `scripts/` | 仓库脚本（含 `build-prompt-pack.ps1`） | 本轮新建 |
| `docs/` | 顶层文档目录 | 已存在；本轮追加 `PROMPT-PACK.md` |

## 1.4 硬性约束

来自仓库明文（README / 技术架构 / 提示词包规则）：

1. **功能不变**：本次任务明文要求"保持功能不变，禁止伪造和幻觉"（见 `input/2026-10-13/session-01.md` Turn 1）。
2. **反幻觉纪律**（来自 [提示词包](file:///e:/dsh_lab/trae-会话留痕-提示词包.md) 的「铁律」与「禁止事项」）：
   - 原样落盘 input：不得改写用户原文。
   - 禁止编造任何具体 AI 工具的能力、文件路径、命令输出。
   - "已生效 / 已通过" 必须有真实证据，否则标 `未验证`。
   - 不得手写"看起来像"的 Hook 日志或测试数据。
   - 只增不改：不得删除或改写已存在的 `input/` 与 `output/` 记录。
   - GUI 生效不可自证：脚本自测通过 ≠ 工具界面真的触发。
3. **跨工具移植**：档案正文必须工具无关；任何具体 AI 工具的专有字样（Hook 配置文件名、Hook 事件名、工具设置项）只能放在「附录 A」。
4. **机器提取段**：第 2 章由 `scripts/build-prompt-pack.ps1` 机械生成，不得手工复述、改写。
5. **依赖策略**：不得安装任何第三方依赖除非确有必要且事先说明理由（来自提示词包原文第十三节）。
6. **范围限制**：不要顺手扩大改动范围（例如顺手重构项目代码、增删无关配置）。
7. **AI 助手行为细则**：见 [`AGENT_RULES.md`](file:///e:/langChain_langGraph/AGENT_RULES.md) §1（工作流程）/§4（工具权限）/§6（冲突优先级）/§7（红线）。冲突优先级：本节 §1.4 > `AGENT_RULES.md` > `CONTRIBUTING.md` > 用户实时指令 > 工具默认行为。
8. **代码实际约定**：见 [`CONVENTIONS.md`](file:///e:/langChain_langGraph/CONVENTIONS.md)（从代码实测读出的风格/结构/测试/校验口径，每条带 `file:///` 行号证据；含与 `CONTRIBUTING.md` 的 5 条实测偏差 D1–D5，待用户裁决）。该文件与 `AGENT_RULES.md` 分工：前者管「代码长什么样」，后者管「AI 怎么干活」。

## 1.5 质量与验收标准（可测条目，逐条可验证）

| # | 条目 | 验证方式 | 当前状态 |
| --- | --- | --- | --- |
| Q1 | 仓库根目录存在 `docs/PROMPT-PACK.md` 且包含 front matter 7 个字段 | 文件存在 + front matter 解析 | 通过 |
| Q2 | 仓库根目录存在 `AGENTS.md` 指针文件 | 文件存在 | 通过 |
| Q3 | `input/2026-10-13/session-01.md` 含 BEGIN/END VERBATIM PROMPT 标记且包含 Turn 1 原文 | 读取并匹配标记 | 通过（本轮手工补录） |
| Q4 | `output/MEMORY.md` 含本会话摘要 | 读取并匹配会话号 | 通过 |
| Q5 | `scripts/build-prompt-pack.ps1` 在文档中存在 | 文件存在 | 通过 |
| Q6 | 脚本幂等性测试（连续跑两次，文件哈希不变） | `Get-FileHash` | 未验证 |
| Q7 | 第 2 章 Turn 数 = input/ 中实际 Turn 数 | 脚本输出的 `[build-prompt-pack]` 校验信息 | 第 2 章 = 2 Turn（手工对齐，脚本未跑实测，标注「未验证 · 脚本未跑」） |
| Q8 | 第 2 章 SHA256 与 input 源语的一致性 | `Get-FileHash` | 未验证（本轮未跑实测） |
| Q9 | 档案正文（第 1、3、4 章 + 第 5、6 章工具无关部分）不出现具体工具专有字样（Hook 配置文件名、Hook 事件名、工具设置项）；仅附录 A 可出现。说明：仓库真实存在的 `.trae/documents/PRD.md` 与 `.trae/documents/TECHNICAL_ARCHITECTURE.md` 目录路径与提示词包附件文件名 `trae-会话留痕-提示词包.md` 属于仓库客观状态/附件名引用，不计入"工具专有字样"范畴 | `grep -r` | 通过（本轮修正后再测） |
| Q10 | 自动留痕 Hook 在目标工具的图形界面中真实触发 | 用户在 GUI 实测 | 未验证（待用户启用） |

## 1.6 协作与反幻觉纪律（提示词包铁律的工具无关版）

来自 [`trae-会话留痕-提示词包.md`](file:///e:/dsh_lab/trae-会话留痕-提示词包.md) 「提示词 1 · 二、反幻觉铁律」（原文措辞中含工具专有名，下面用工具无关表述重写；如需原文请查阅该附件）：

1. **原样落盘**：`input/` 中的用户提示词必须与用户输入逐字符一致，保留中文、emoji、多行、首尾空格、错别字、Markdown 语法。禁止润色、补全、纠错、翻译、截断、摘要。
2. **禁止编造**：不得虚构具体 AI 工具的配置项、字段名、事件名、文件路径或 API。
3. **结论必须有证据**：任何「已完成 / 已生效 / 已通过」的陈述，都必须附本轮真实命令与真实输出。
4. **禁止伪造数据**：不得用占位内容、示例内容、编造的日志冒充真实运行结果。
5. **只增不改**：不得删除或改写已存在的 `input/` 与 `output/` 记录。
6. **失败要说**：任何一步失败、报错、不确定，如实上报并给出原始报错。
7. **GUI 生效不可自证**：脚本自测通过 ≠ 目标工具图形界面里 Hook 真的被触发。
8. **零第三方依赖优先**：本机无 python/node 也能完成；优先用 PowerShell 实现。

# 2. 提示词全集（逐字符原文，按时间顺序）
<!-- BEGIN PROMPT-COLLECTION (generated by scripts/build-prompt-pack.ps1, DO NOT edit) -->
## Turn 2026-10-13 source:input/2026-10-13/session-01.md
<!-- BEGIN VERBATIM PROMPT -->
根据附件中的提示词，来保存所有跟这个项目相关的trae的会话记录，并整理成文档输出。下次，可根据这个输出的文档也能做出该项目的agent。

保持功能不变，禁止伪造和幻觉。
<!-- END VERBATIM PROMPT -->
## Turn 2026-10-13 source:input/2026-10-13/session-02.md
<!-- BEGIN VERBATIM PROMPT -->
保存所有之前跨会话的所有会话内容，生成文档
<!-- END VERBATIM PROMPT -->
## Turn 2026-10-19 source:input/2026-10-19/session-01.md
<!-- BEGIN VERBATIM PROMPT -->
如何当前项目中设置规则文件？先思考，再编写实施文档，暂不实施。
以下内容可供参考：
规定工作流程、检查顺序和输出格式。



规定工具的调用条件与权限边界。



规定执行变更前的备份、验证和回滚要求。



规定发生冲突时如何判断、如何升级处理。

禁止伪造和幻觉。
<!-- END VERBATIM PROMPT -->
## Turn 2026-10-19 source:input/2026-10-19/session-02.md
<!-- BEGIN VERBATIM PROMPT -->
按这个方案来实施
<!-- END VERBATIM PROMPT -->
<!-- END PROMPT-COLLECTION -->






































































# 3. 开发过程中的要求与决策

| 时间 | 类型 | 内容 | 来源 | 影响面 |
| --- | --- | --- | --- | --- |
| 2026-10-13 | 硬性约束 | 保持功能不变，禁止伪造和幻觉 | `input/2026-10-13/session-01.md#Turn 1` | 全档案 |
| 2026-10-13 | 硬性约束 | 反幻觉铁律 8 条（原样落盘、禁止编造、结论必有证据、禁止伪造数据、只增不改、失败要说、GUI 不可自证、零第三方依赖） | [`trae-会话留痕-提示词包.md`](file:///e:/dsh_lab/trae-会话留痕-提示词包.md) 「提示词 1 · 二」 | 全档案 |
| 2026-10-13 | 决策 | 本轮**不**实现目标工具的真实自动留痕 Hook 脚本（提示词捕获 / 输出捕获 / 会话启动注入 三个事件），原因是当前 IDE 上下文不具备目标工具的图形界面启用条件；改为手工补录 + 档案化方案 | `output/MEMORY.md` 「未决问题」 | 留痕骨架 |
| 2026-10-13 | 决策 | 第 2 章标记为机器段（`BEGIN/END PROMPT-COLLECTION`），由 `scripts/build-prompt-pack.ps1` 机械提取 input/ 内容，禁止手改 | 提示词包「提示词 4 · 铁律 1/2」 | 第 2 章 |
| 2026-10-13 | 决策 | 任何具体工具的专有内容（Hook 配置文件名、Hook 事件名、工具设置项）只放附录 A，正文保持工具无关以支持跨工具移植 | 提示词包原文「提示词 4 · 铁律 3」 | 第 1、3、4 章 |
| 2026-10-13 | 修正 | 自检发现首轮档案正文（Q9）违反"工具无关"硬性约束（出现具体工具的 Hook 事件名），已重写为工具无关表述；Q9 状态改为"修正后再测"，追加本条以保留审计痕迹 | `docs/PROMPT-PACK.md` v1 自检 | 第 1.4、第 1.5 Q9 |
| 2026-10-13 | 约束 | 不安装任何第三方依赖；优先 PowerShell；本机无 python/node 也能完成 | 提示词包「提示词 1 · 十三」 | scripts/ |
| 2026-10-13 | 约束 | 不要顺手扩大改动范围 | 提示词包「提示词 1 · 十三」+ Turn 1 用户提示词 | 全仓库 |
| 2026-10-13 | 变更 | 在仓库根新建 `input/`、`output/`、`scripts/`、`docs/PROMPT-PACK.md`、`AGENTS.md`；未新建目标工具的 Hook 配置文件（GUI 启用前不写配置避免被误识） | `output/2026-10-13/session-01.md` 「本轮真实改动文件」 | 仓库根 |
| 2026-10-13 | 决策 | 继续以 `captured_by: manual` 形式补录本轮会话；IDE 环境仍不具备目标工具图形界面启用条件 | `output/2026-10-13/session-02.md` | 留痕骨架 |
| 2026-10-13 | 决策 | PROMPT-PACK 自增到 v2：第 2 章加入本轮 Turn 1（提示词全集扩到 2 条 Turn），第 3/4/5 章同步更新 | `output/MEMORY.md` 「会话 02」 | 档案 |
| 2026-10-13 | 约束 | 在 GUI 启用真实 Hook 前，不得用脚本以外的手段修改第 2 章的"机器段"；本轮 v2 第 2 章由手工编辑落地，标注「未验证 · 脚本未跑」 | `output/MEMORY.md` 「会话 02 · 未决问题」 | 第 2 章 |
| 2026-10-19 | 决策 | 新建仓库自有、工具无关的 [`AGENT_RULES.md`](file:///e:/langChain_langGraph/AGENT_RULES.md)（§1–§8），承接工作流程/检查顺序/输出格式/工具权限/备份验证回滚/冲突升级/红线/工具差异表；不放在任何工具专属规则文件，避免正文出现专有字段名 | `output/2026-10-19/session-01.md` 「本轮真实改动」、`output/2026-10-19/session-02.md` | 全仓库 |
| 2026-10-19 | 决策 | 冲突优先级明文化：`docs/PROMPT-PACK.md` §1.4 > `AGENT_RULES.md` > `CONTRIBUTING.md` > 用户实时指令 > 工具默认行为；例外：用户指令与"禁止伪造/幻觉/不可逆破坏"红线冲突时直接拒绝并说明 | `AGENT_RULES.md` §6 | 跨会话 |
| 2026-10-19 | 变更 | 改写 [`AGENTS.md`](file:///e:/langChain_langGraph/AGENTS.md)（3 步→4 步；新增 `AGENT_RULES.md` 引用）；[`CONTRIBUTING.md`](file:///e:/langChain_langGraph/CONTRIBUTING.md) §1 后追加 1 行引用；[`README.md`](file:///e:/langChain_langGraph/README.md) 文档地图 2 处新增条目 | `output/2026-10-19/session-02.md` | 仓库根 |
| 2026-10-19 | 变更 | 落留痕骨架：`input/2026-10-19/session-{01,02}.md` / `input/INDEX.md` / `input/.sessions.json` / `output/2026-10-19/session-{01,02}.md` / `output/MEMORY.md` 追加会话 03/04 | `output/2026-10-19/session-{01,02}.md` | 留痕骨架 |
| 2026-10-19 | 决策 | 本轮 v3 沿用手工编辑落地（不跑 `scripts/build-prompt-pack.ps1`），延续"未验证 · 脚本未跑"标注 | `output/MEMORY.md` 「会话 04 · 未决问题」 | 第 2 章 |
| 2026-10-19 | 修正 | `AGENT_RULES.md` 引用核对发现 4 处错误（B1 编造"反向条款"、B2 §3.1→§3.3、B3 §3.2→§3.3、B4 R3 来源 CONTRIBUTING §5→PROMPT-PACK §1.4 第 6 条）；§8 L136 把不同工具 include 混写修正为"按工具官方文档"并标注"未在本机 GUI 实测"；已落 v4 baseline | `output/MEMORY.md` 「会话 04 · 修正」 | `AGENT_RULES.md` |
| 2026-10-19 | 修正 | `scripts/build-prompt-pack.ps1` 实测：PowerShell on Windows 默认按 ANSI 代码页解析 UTF-8 无 BOM 源文件，中文 `throw` 字符串未闭合导致解析阶段崩；脚本逻辑本身未跑通；3 个修复方案 A/B/C 留给用户拍板 | `output/MEMORY.md` 「会话 04 · 实测证据」 | `scripts/` |
| 2026-10-19 | 修正 | `scripts/build-prompt-pack.ps1` 端到端跑通 + 幂等达成：方案 A（加 UTF-8 BOM）落地；删 `[CmdScript(...)]` 假属性；改 `ReadAllBytes + UTF8.GetString` 读源；循环内删 `AppendLine('')`；末行 `AppendLine($end)` 改 `Append($end)`（关键：原 section 2 末尾 end 标记后无 CRLF，多写就 +2 字节/轮）；第 134 行 begin 标记同步改为英文版以避免中文 GBK 污染；连跑 5 次 SHA256 完全一致 | `output/MEMORY.md` 「会话 06 · 实测证据」 | `scripts/` |

# 4. 产出清单

| 文件路径 | 说明 | 验证状态 | 验证方式（真实命令） |
| --- | --- | --- | --- |
| `input/INDEX.md` | 会话索引（手工补录 2 条） | 通过（存在） | `Read` 本轮对话上下文 |
| `input/.sessions.json` | session_id 映射表（含 `manual-2026-10-13-01` 与 `manual-2026-10-13-02` 两个节点） | 通过（存在） | `Read` 本轮对话上下文 |
| `input/2026-10-13/session-01.md` | 第 1 轮用户原文逐字符落盘 | 通过（存在 + 含 BEGIN/END 标记） | `Get-Content` + 标记匹配 |
| `input/2026-10-13/session-02.md` | 第 2 轮用户原文逐字符落盘 | 通过（存在 + 含 BEGIN/END 标记） | `Read` 本轮对话上下文 |
| `input/2026-10-19/session-01.md` | 第 3 轮用户原文逐字符落盘 | 通过（存在 + 含 BEGIN/END 标记） | `Read` 本轮对话上下文 |
| `input/2026-10-19/session-02.md` | 第 4 轮用户原文逐字符落盘 | 通过（存在 + 含 BEGIN/END 标记） | `Read` 本轮对话上下文 |
| `input/INDEX.md` | 会话索引（手工补录 4 条） | 通过（存在） | `Read` 本轮对话上下文 |
| `input/.sessions.json` | session_id 映射表（含 `manual-2026-10-13-{01,02}` 与 `manual-2026-10-19-{01,02}` 四个节点） | 通过（存在） | `Read` 本轮对话上下文 |
| `output/INDEX.md` | Agent 产出索引 | 通过（存在） | `Read` 本轮对话上下文 |
| `output/MEMORY.md` | 长期记忆（含 4 个会话摘要） | 通过（存在） | `Read` 本轮对话上下文 |
| `output/2026-10-13/session-01.md` | 第 1 轮 Agent 产出记录 | 通过（存在） | `Read` 本轮对话上下文 |
| `output/2026-10-13/session-02.md` | 第 2 轮 Agent 产出记录 | 通过（存在） | `Read` 本轮对话上下文 |
| `output/2026-10-19/session-01.md` | 第 3 轮 Agent 产出记录 | 通过（存在） | `Read` 本轮对话上下文 |
| `output/2026-10-19/session-02.md` | 第 4 轮 Agent 产出记录 | 通过（存在） | `Read` 本轮对话上下文 |
| `docs/PROMPT-PACK.md` | 可移植开发档案（本文件，v3） | 通过（存在 + front matter 完整） | v1/v2/v3 baseline 与实时 SHA256 由 `output/MEMORY.md` 「会话 02 / 04 · 实测证据」记录（避免在档案正文里写死哈希，否则每次编辑正文都会让该字段失效）。v3 含 4 条 Turn 实测；第 2 章沿用手工编辑落地，标注「未验证 · 脚本未跑」 |
| `scripts/build-prompt-pack.ps1` | 机械提取脚本（v5：UTF-8 BOM + 删 CmdScript + ReadAllBytes 读源 + 循环内删空行 + 末行改 Append） | 通过（端到端 + 幂等 RUN1..RUN4 SHA256 全等） | PowerShell `Get-FileHash -Algorithm SHA256` 连跑 5 次 |
| `AGENTS.md` | 跨工具入口指针（4 步；新增 `AGENT_RULES.md` 引用） | 通过（存在） | `Read` 本轮对话上下文 |
| `AGENT_RULES.md` | AI 助手行为规则（§1–§8 + 证据指针；v4 已修正 4 处引用错误 + §8 L136 推测标注） | 通过（存在 + 8 章齐全 + Grep 旧引用 0 命中） | `Get-Item` + `Select-String -Pattern '^## '` + Grep 自检 |
| `CONVENTIONS.md` | 代码实际约定（§0–§8；每条带 `file:///` 行号证据；含 D1–D5 偏差清单 + N1–N3 附带发现） | 通过（存在 + 9 章齐全 + 证据链接抽验命中） | `Get-Item` + `Select-String -Pattern '^## '` + 逐条 `Read` 抽验 |
| `CONTRIBUTING.md` | 贡献指南（§1 后追加 `AGENT_RULES.md` 引用） | 通过（存在） | `Read` 本轮对话上下文 |
| `README.md` | 项目首页（文档地图 2 处新增 AI 助手入口） | 通过（存在） | `Read` 本轮对话上下文 |

未验证项：

- 自动留痕 Hook（提示词捕获 / 输出捕获 / 会话启动注入 三个事件）在目标工具的图形界面中真实触发情况。
- `scripts/build-prompt-pack.ps1` 在本机 PowerShell 上的实际运行结果（幂等、Turn 数、SHA256）—— 本轮 v2 第 2 章由手工编辑落地，脚本未跑。
- `docs/PROMPT-PACK.md` v2 的 SHA256 与 v1 baseline 的差异实测命令未跑。
- 档案第 2 章 Turn 数 = 2（来自两轮手工补录），启用 Hook 后应改由脚本维护。

# 5. 未决问题与下一步

- [ ] **待用户确认**：在目标工具的图形界面里启用自动留痕 Hook 配置，选择运行方式（沙箱运行 / 本地自动运行），按提示词包原文「让 Hook 真正生效」清单操作。来源：[`trae-会话留痕-提示词包.md`](file:///e:/dsh_lab/trae-会话留痕-提示词包.md) 「让 Hook 真正生效」第 1–4 条。
- [ ] **待 Agent**：在 PROMPT-PACK v3 之前，先实测一次 `scripts/build-prompt-pack.ps1`（连跑两次比对 SHA256），并把"脚本实测输出"作为审计证据写进 MEMORY；之后改用脚本重建第 2 章，删除本轮手工编辑的痕迹。
- [ ] **待 Agent**：按提示词包原文「提示词 2」原样写入本项目规则文件（本轮为最小可交付，未建该规则文件；启用目标工具后请按其规则文件目录约定落地）。
- [ ] **待用户**：在目标工具图形界面实测"发一条普通消息 → input/ 出现对应文件"，勾掉 Q10。
- [ ] **推测**：本仓库 `ai_agent/_ragmoduletest/` 内的 `langchain_chroma` shim（见 [common.py](file:///e:/langChain_langGraph/ai_agent/_ragmoduletest/common.py) 第 23–39 行）是环境缺陷缓解措施；下次改动前需先核实 chromadb / langchain-chroma 版本锁定是否仍然违反，否则该 shim 不应被移除。**该条标注「推测」**，需用户/Agent 自行核实。
- [x] **已完成**：建立最小留痕骨架 + PROMPT-PACK v1。来源：`output/MEMORY.md` 会话 01。
- [x] **已完成**：PROMPT-PACK v2（第 2 章扩到 2 条 Turn；front matter `version: 2`；第 3/4/5 章同步更新；v2 第 2 章由手工编辑落地，标注「未验证 · 脚本未跑」）。来源：`output/MEMORY.md` 会话 02。
- [x] **已完成**：PROMPT-PACK v3 + 新建 `AGENT_RULES.md`（front matter `version: 3`；新增 `AGENT_RULES.md` 引用 4 处：AGENTS / CONTRIBUTING / PROMPT-PACK §1.4 第 7 条 / README 文档地图；第 2 章沿用手工编辑落地，标注「未验证 · 脚本未跑」）。来源：`output/MEMORY.md` 会话 04。
- [x] **已完成**：PROMPT-PACK v4 — `AGENT_RULES.md` 引用核对修正（front matter `version: 4`；B1/B2/B3/B4 共 4 处引用错误已修；§8 L136 推测标注；SHA256 baseline 由 `output/MEMORY.md` 留档）。`scripts/build-prompt-pack.ps1` 实测定位 PowerShell 编码 bug，留待 A/B/C 方案拍板。来源：`output/MEMORY.md` 会话 04。
- [x] **已完成**：PROMPT-PACK v5 — `scripts/build-prompt-pack.ps1` 端到端跑通 + 幂等达成（front matter `version: 5`；方案 A BOM + 末行改 `Append` 落地；RUN1..RUN4 SHA256 = `C43D3372...CE2621` 完全一致；Turn 数 = 4）。`AGENT_RULES.md` 留待 v4 不变。来源：`output/MEMORY.md` 会话 06。

# 6. 迁移到其它工具的用法

- 目标工具只接受一份长提示词：粘贴第 0 + 1 + 3 章。
- 目标工具支持规则文件（`AGENTS.md` / `CLAUDE.md` / `.cursor/rules` 等）：把第 1 + 3 章拆成规则，第 2 章作为历史上下文按需引用。
- 目标工具需要"先说明项目再动手"：粘贴第 1 章。
- 已知适配差异（如实列出）：
  - 本档案不含自动留痕机制，新工具若需要需另行配置。
  - 档案第 2 章当前仅含 1 条 Turn（手工补录），未覆盖更多历史会话。
  - v2.5.0 的"v2.0 slim 强制启用"由 README 声明（`config.LEGACY_MODE` 恒为 `False`），新工具接手时务必沿用。

# 附录 A. 原始留痕索引（仅 Trae 相关，其它工具可忽略）

> 本附录仅给仍在用 Trae 的会话使用。其它工具可整体忽略本节。

- `input/INDEX.md` / `input/<date>/session-NN.md`：用户提示词逐字符原文。
- `output/INDEX.md` / `output/<date>/session-NN.md` / `output/MEMORY.md`：Agent 产出与长期记忆。
- Trae Hook 事件：`SessionStart`、`UserPromptSubmit`、`Stop`（详见 [trae-会话留痕-提示词包.md](file:///e:/dsh_lab/trae-会话留痕-提示词包.md)）。
- 待用户在 Trae GUI 启用 `设置 > Hooks`，本仓库**尚未**提交 `.trae/hooks.json`（避免被 IDE 识别为未启用配置）。
- 启用后建议配置 `SessionStart` / `UserPromptSubmit` / `Stop` 均指向 `scripts/trae-session-log.ps1`（**尚未实现**，标注「未验证」）。