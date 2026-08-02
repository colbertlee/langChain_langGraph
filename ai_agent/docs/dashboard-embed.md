# Dashboard 嵌入指南（Day 21）

## 它是什么

`tools/archive_dashboard.py` 输出 `tests-archive/dashboard.svg`，多 panel：
- **Panel 1**：archive trend（passed / failed / errored / ran_ratio%）
- **Panel 2**：evals（pass_rate 折线 + latency 柱状）
- **Panel 3**：chat latency（按阈值上色：绿 / 橙 / 红）

输出特点：
- **零硬依赖**：纯 stdlib，**无 matplotlib / plotly**；
- **矢量 SVG**：可缩放到任意分辨率不失真；
- **3 种 size**：默认 1080×360；单 panel 默认 760×360。

## 怎么生成

```bash
# 多 panel（默认）
python tools/archive_dashboard.py

# 仅 archive trend
python tools/archive_dashboard.py --panels archive

# 仅 evals
python tools/archive_dashboard.py --panels evals

# 仅 chat latency
python tools/archive_dashboard.py --panels chats
```

数据源（缺失则该 panel 显示 "no xxx data"）：

| Panel | 数据来源 | 默认路径 |
|-------|---------|----------|
| archive trend | `tests-archive/acceptance/<ts>/summary.json` | 自动 |
| evals | 用户提供的 JSON list | `tests-archive/evals_history.json` |
| chat latency | 用户提供的 JSON list | `tests-archive/chat_latency.json` |

evals/chat JSON 格式：

```jsonc
// tests-archive/evals_history.json
[
  {"ts": "2026-07-26T10:00", "pass_rate": 0.95, "total": 30, "latency_ms": 1200},
  {"ts": "2026-07-26T11:00", "pass_rate": 0.92, "total": 28, "latency_ms": 1500}
]

// tests-archive/chat_latency.json
[
  {"ts": "2026-07-26T12:00", "latency_ms": 320},
  {"ts": "2026-07-26T12:01", "latency_ms": 450}
]
```

## 怎么嵌入 README

### 方式 1：GitHub Pages（推荐）

1. 把 SVG 推到 `gh-pages` 分支的 `dashboard.svg` 路径；
2. README 写：

```markdown
## 📊 Archive Observability Dashboard

![archive dashboard](https://raw.githubusercontent.com/<org>/<repo>/gh-pages/dashboard.svg)
```

3. CI 触发方式：

```yaml
# .github/workflows/deploy-pages.yml
- name: Deploy dashboard to Pages
  run: |
    mkdir -p public
    cp tests-archive/dashboard.svg public/dashboard.svg
    git checkout gh-pages
    cp public/dashboard.svg dashboard.svg
    git commit -am "update dashboard"
    git push
```

### 方式 2：GitHub release（**已自动接入**）

`release-build.yml` 在每次 release-tag 后会：

1. 把 `dashboard.svg` 上传为 artifact（保留 365 天）；
2. 用 `cairosvg` 转 PNG（GitHub release notes 不支持 SVG 内嵌）；
3. 把 dashboard.png 嵌入 release notes。

发布后 GitHub release page 会显示 dashboard。

### 方式 3：直接用 SVG（`<img>` 标签）

GitHub README **支持 SVG `<img>` 引用**：

```markdown
## 📊 Archive Observability Dashboard

<img src="tests-archive/dashboard.svg" alt="dashboard" width="1080"/>
```

> ⚠️ **限制**：必须是相对路径或 `raw.githubusercontent.com` URL；
> SVG 文件必须 commit 到仓库。

### 方式 4：导出 PNG 本地嵌

如需 PNG：

```bash
pip install cairosvg
python -c "
import cairosvg
cairosvg.svg2png(
    url='tests-archive/dashboard.svg',
    write_to='tests-archive/dashboard.png',
    output_width=1080
)
"
```

## 推荐 layout

### README 顶部

```markdown
# AI Agent

[![CI](...)](...)
[![Releases](...)](...)
[![Docs](...)](...)

## 📊 Observability

![dashboard](https://raw.githubusercontent.com/<org>/<repo>/gh-pages/dashboard.svg)

*Latest: archive trend, evals pass_rate, chat latency — auto-updated by CI.*
```

### README 单独章节

```markdown
## 🩺 Health Dashboard

实时数据由 weekly-archive.yml + release-build.yml 维护。

![dashboard](https://raw.githubusercontent.com/<org>/<repo>/gh-pages/dashboard.svg)

图例：
- 🟢 passed / 绿 = 良好
- 🟠 failed / 橙 = 警告
- 🔴 errored / 红 = 严重
- 🔵 ran_ratio% / 蓝虚线 = 可跑率
```

## 维护建议

| 频率 | 动作 |
|------|------|
| 每次 PR merge | weekly-archive.yml 自动跑一次 |
| 每次 release-tag | release-build.yml 跑 + 上传 dashboard |
| 团队周会前 | 看 TREND.md / CHANGELOG.md / dashboard.svg 三件套 |
| 季度 review | 看 archive acceptance ran_ratio 趋势 |

## 故障排查

| 现象 | 排查 |
|------|------|
| Panel 显示 "no xxx data" | 检查数据源 JSON 路径 / 内容 |
| SVG 在浏览器显示空白 | viewBox 或 fill 字段问题；用 `python -c "import xml.etree.ElementTree as ET; ET.parse('tests-archive/dashboard.svg')"` 验证 |
| Slack 不显示上传的图片 | Slack 需 `files.upload` 而非 `files.upload_v2`；检查 token 权限 scope |
| release notes 没图 | `cairosvg` 未装；可手动 `pip install cairosvg` 或保留 SVG 链接 |
| dashboard.svg 文件大 | 用 `--limit 5` 减少 panel 1 数据点 |