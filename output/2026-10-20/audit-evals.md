# audit-evals
---
scope: ai_agent/evals/runs/**/summary.json
runs_scanned: 35

## 失败占比

| status | count | pct |
| --- | ---: | ---: |
| ok | 0 | n/a |
| fail | 0 | n/a |
| other/parse_error | 35 | - |

## 近 30 天

- 近 30 天有 mtime 的 run 数: 4
- 其中失败: 0
- 失败率: 0.0%

## 月度趋势（按 mtime）

| month | total | fail |
| --- | ---: | ---: |
| 2026-09 | 35 | 0 |

## 失败原因 Top-10（按字段名 fail_reason/error/reason 抓）

- （字段未提取到，原因结构未知；不影响占比统计）

## RAG 回归风险面（按 run 名前缀归类）

| prefix | total | fail | fail_rate |
| --- | ---: | ---: | ---: |
| `harness` | 15 | 0 | 0% |
| `20260726` | 12 | 0 | 0% |
| `20260903` | 4 | 0 | 0% |
| `rag` | 4 | 0 | 0% |

_摸排口径：`summary.json.status` 字段；若不存在则记 `unknown`；30 天窗口以文件 mtime 落点。_