# 会话 2026-10-19 / manual-2026-10-19-02 · 产出

> 本轮 Turn 1：用户回复"按这个方案来实施"。

## 本轮真实改动

| 文件 | 状态 | 行数变化 |
|---|---|---|
| `AGENT_RULES.md` | 新建 | +1 文件（§1–§8 + 证据指针） |
| `AGENTS.md` | 改写 | 1 → 4 步；新增 `AGENT_RULES.md` 引用 |
| `CONTRIBUTING.md` | 追加引用 | §1 后插入 1 行引用 |
| `docs/PROMPT-PACK.md` | §1.4 追加第 7 条 | 冲突优先级明文 |
| `README.md` | 文档地图追加 | 2 处新增条目 |
| `input/2026-10-19/session-01.md` | 新建 | 用户 Turn 1 原文 |
| `input/2026-10-19/session-02.md` | 新建 | 用户 Turn 2 原文 |
| `input/INDEX.md` | 追加 2 行 | 2026-10-19 两条 |
| `input/.sessions.json` | 追加 2 节点 | manual-2026-10-19-01/02 |
| `output/2026-10-19/session-01.md` | 新建 | 本会话产出 |
| `output/2026-10-19/session-02.md` | 新建 | 本会话产出 |
| `output/MEMORY.md` | 追加会话 03 | 留档 SHA256 baseline |

## 实测证据（PowerShell `Get-FileHash` SHA256）
```
178B63BCE92BE900847BE287601989150151E654E5E460E22BDB5FE8D5A5E11A  AGENT_RULES.md
E53DBB53F36D08F80C131DCE2ACA8E172D525686E8B084A2D167E9403101D7D3  AGENTS.md
46C7D493935C5C028DDC732293EBA0E7B2AAC322E60E46F5CB291A1BBF643811  CONTRIBUTING.md
AB7DE0BDC3C9D30C26E6CC90755C97188B13A8BFC530F7CB8011DF77FD8FB246  docs/PROMPT-PACK.md
3379DA9FA81625DB55CEFB5CB7DFD943AE36FB332FD6B66C94233C3AAB06E83B  README.md
```

## 验证清单（实测）
| # | 检查 | 结果 |
|---|---|---|
| R1 | `AGENT_RULES.md` 存在（9229 字节） | 通过 |
| R2 | 8 章齐全（§1–§8）+ 证据指针小节 | 通过（9 个 `## ` 行） |
| R3 | AGENT_RULES 正文不含工具专有字段名 | 通过（Grep 0 命中） |
| R4 | `AGENTS.md` / `CONTRIBUTING.md` / `docs/PROMPT-PACK.md` 入口引用 | 通过（各 1+ 处） |
| R5 | `README.md` 文档地图更新 | 通过（2 处新增） |
| R6 | SHA256 baseline 落档 | 通过（本文件） |

## 未验证项
- 工具差异适配表（§8）各工具实际读取本文件的入口未在本机图形界面实测。
- `docs/PROMPT-PACK.md` §1.4 第 7 条新增后未跑 `scripts/build-prompt-pack.ps1` 实测重建第 2 章；本次不涉及第 2 章，仅追加 §1.4 单行，按"机器段不得手改"原则未触 §2。
