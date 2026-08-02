# Archive 过夜验收（Day 17/18）

## 它是什么

每次 release 前（或任何需要知道"归档里还有多少能跑"的时机），跑：

```bash
python tools/archive_acceptance.py                # 默认超时 120s
python tools/archive_acceptance.py --strict       # 任意 fail/error → 退出 1
python tools/archive_acceptance.py --timeout 600  # CI 用更长超时
```

输出落到：

- `tests-archive/ACCEPTANCE.md` — 人类可读的最新报告
- `tests-archive/acceptance/<YYYYMMDD_HHMMSS>/summary.json` — 时间序列历史
- `tests-archive/acceptance/<YYYYMMDD_HHMMSS>/pytest.log` — 原始输出

## 趋势分析

```bash
python tools/archive_trend.py --output tests-archive/TREND.md
python tools/archive_trend.py --diff --strict    # 退步 → exit 1
```

`TREND.md` 输出形态：

```markdown
| 时间 | files | passed | failed | errored | skipped | ran_ratio |
| ...                              |
| 20260726_173500 | 21 | 5  | 14 | 2 | 0 | `5/21`  |
| 20260726_174125 | 21 | 8  | 12 | 1 | 0 | `8/21`  |

## 最近一次 vs 上一次
- 🟢 **passed**: 5 → 8 (+3)
- 🟢 **failed**: 14 → 12 (-2)
- 🟢 **errored**: 2 → 1 (-1)
- ran_ratio: `5/21` → `8/21`
```

🟢=改善；🔴=退步；⚪=不变。**`--strict` 在退步时退出 1**。

## CI 整合

`release-build.yml` 已经把 archive-acceptance 加为 **gate job**：

```yaml
jobs:
  archive-acceptance:
    name: archive-acceptance-gate
    # 跑 acceptance --strict + trend report + 失败时开 issue
  build:
    needs: archive-acceptance
  release:
    needs: [build, archive-acceptance]
```

触发：

- `git push --tags v*.*.*`
- `Actions → release-build → Run workflow`

任何 fail / error → release 流程停在 archive-acceptance gate。

## 数据沉淀（git）

`tests-archive/acceptance/<ts>/summary.json` 必须 commit：

- 提供了"跨次 diff"的基础；
- 团队 review 时有历史可查；
- 不需要额外的数据库 / 服务。

`.gitignore` 已经把体积大的 pytest.log 与 __pycache__ 排除，**只留 summary.json**。

## 量化 KPI 解读

| 字段 | 含义 |
|------|------|
| `files` | 归档案总文件数 |
| `passed` | 整文件所有 test 都 PASS 的数 |
| `failed` | 至少一个 test FAIL 的数 |
| `errored` | collect 阶段 import 错 / 异常 |
| `skipped` | 至少一个 test SKIP |
| `ran_ratio` | `passed / (passed + failed + errored + skipped)`，即"可跑率" |

**释放节奏建议**：

- 每个 release 前：`python tools/archive_acceptance.py --strict`
- CI 自动算 TREND.md diff，存档
- 每个 release 顺手归档（移到 `tests-archive/scripts/`）若干 `errored` 文件
- 目标：3-4 个 release 内 `tests-archive/tests/` 缩到 < 10 文件 → 可考虑删除整个目录