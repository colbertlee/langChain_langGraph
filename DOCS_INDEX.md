# 📚 项目文档入口(Documentation Portal)

> **副标题**:一站式导航 — 所有文档的"目录的目录"。
> **最后更新**:2026-08-02 · **当前版本**:v0.4.16

---

## 📋 本文档元信息

| 项 | 值 |
|---|---|
| 🎯 **目标读者** | 所有人(第一次打开项目的人) |
| ⏱️ **预计阅读** | 5 分钟(全文) / 30 秒(只看"3 秒决策树") |
| 📊 **难度** | ⭐ |
| 🎯 **本文档目的** | 让你**3 秒找到**任何问题的答案 |

---

## 🎯 3 秒决策树

```
你想要什么?
   │
   ├─ 🚀 "我想立刻跑起来" ──→ [ai_agent/USAGE.md](ai_agent/USAGE.md) §1
   │
   ├─ 📖 "我刚接手,想了解全貌" ──→ [README.md](README.md) §1
   │
   ├─ ⬆️ "我想升级版本" ──→ [ai_agent/UPGRADE.md](ai_agent/UPGRADE.md)
   │
   ├─ 🆕 "v0.4.16 改了什么?" ──→ [ai_agent/RELEASE_NOTES.md](ai_agent/RELEASE_NOTES.md)
   │
   ├─ 🏗️ "架构怎么设计?" ──→ [ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md](ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md)
   │
   ├─ 🔧 "我想看 8 个 Middleware Hook 怎么用" ──→ [ai_agent/agent_middleware.md](ai_agent/agent_middleware.md)
   │
   ├─ 🛠️ "我要排查 bug / 部署 / 打包" ──→ 下方分类索引
   │
   └─ 🆘 "完全不知道从哪开始" ──→ [ai_agent/USAGE.md](ai_agent/USAGE.md) §1(5 分钟)
```

---

## 📊 文档全景图(可视化)

```
                                ┌──────────────────────────┐
                                │   README.md              │ ← 总览 / 兼容性矩阵 / 选型对比
                                │   (本仓库根)              │
                                └────────────┬─────────────┘
                                             │
              ┌──────────────────────────────┼──────────────────────────────┐
              │                              │                              │
              ▼                              ▼                              ▼
       ┌─────────────┐               ┌─────────────┐                ┌─────────────┐
       │ ai_agent/   │               │ web_console/│                │ 顶层 docs/  │
       │ 后端文档    │                │ 前端文档    │                │ 全局文档   │
       └──────┬──────┘               └──────┬──────┘                └──────┬──────┘
              │                              │                              │
   ┌──────────┼──────────┐         ┌─────────┼─────────┐            ┌─────┼──────┐
   │          │          │         │         │         │            │     │      │
   ▼          ▼          ▼         ▼         ▼         ▼            ▼     ▼      ▼
 USAGE     README    RELEASE    QUICK     .github/   CHANGELOG   API  DIRECTORY  ...
  .md       .md      _NOTES.md   START     *.md       .md         .md   _STR...
   │          │          │
   ├→ UPGRADE  ├→ FEATURES  └→ CHANGELOG
   │          │  _GUIDE
   │          │
   │          └→ agent_middleware.md
   │
   └→ docs/AGENT_ARCHITECTURE_ROADMAP.md
```

---

## 🗂️ 第一层:仓库级文档(根目录)

| 文档 | 为什么存在 | 有什么用 | 谁该读 |
|---|---|---|---|
| **[`README.md`](README.md)** | 项目门面,GitHub 访问第一眼看到的 | 项目定位、兼容性矩阵、5 维度选型对比(对比 LangChain/CrewAI/AutoGen)、架构图、快速链接 | **所有人** |
| **[`CHANGELOG.md`](CHANGELOG.md)** | 顶层变更记录(GitHub Releases 自动生成) | 跨子项目的版本演进、Breaking Changes 顶层视图 | 维护者 / 升级决策者 |
| **[`QUICKSTART.md`](QUICKSTART.md)** | 5 分钟极速体验入口 | 一键 `docker compose up` + 浏览器访问 | 第一次来的人 |
| **[`CONTRIBUTING.md`](CONTRIBUTING.md)** | 规范贡献流程 | PR 模板 / Code Style / 测试要求 | 想贡献代码的人 |
| **[`DISTRIBUTION.md`](DISTRIBUTION.md)** | 多渠道分发说明 | PyPI / Docker / Scoop / Homebrew 的发布流程 | 运维 / 发布者 |
| **[`docs/API.md`](docs/API.md)** | 顶层 API 速查 | 跨子项目的端点索引 | 集成开发者 |
| **[`docs/DIRECTORY_STRUCTURE.md`](docs/DIRECTORY_STRUCTURE.md)** | 目录结构说明 | 整个仓库的目录树 + 每个目录的职责 | 贡献者 / 维护者 |
| **[`.github/SECURITY.md`](.github/SECURITY.md)** | 安全策略 | 漏洞报告流程、披露政策 | 安全研究员 |

> 💡 **根目录文档的逻辑**:**README 是门面,CHANGELOG 是历史,QUICKSTART 是入口,CONTRIBUTING 是规范**。

---

## 🗂️ 第二层:后端子项目文档(ai_agent/)

> 📦 `ai_agent/` 是 Python 后端,LangChain 1.x + LangGraph + MCP 的核心实现。

### 用户面向文档(新用户先读这 3 个)

| 文档 | 为什么存在 | 有什么用 | 谁该读 |
|---|---|---|---|
| 🆕 **[`USAGE.md`](ai_agent/USAGE.md)** | 新手友好的使用说明书 | 5 分钟跑通、9 大任务速查、12 个 FAQ、故障排查流程图、自测题 | 🆕 **第一次用的人** |
| 🆕 **[`UPGRADE.md`](ai_agent/UPGRADE.md)** | 版本升级权威指南 | 兼容性矩阵、生产蓝绿部署、回滚方案、升级前必看清单 | 🏢 **运维 / 老用户** |
| 🆕 **[`RELEASE_NOTES.md`](ai_agent/RELEASE_NOTES.md)** | 最新发布说明 | v0.4.16 亮点(降本 50%+)、决策表、Before/After 对比 | 👀 **想知道"该不该升级"的人** |
| **[`README.md`](ai_agent/README.md)** | 后端项目门面 | 目录结构 / 11 家 Provider / 安装 / API 端点 / 扩展指南 | 所有人 |
| **[`FEATURES_GUIDE.md`](ai_agent/FEATURES_GUIDE.md)** | 功能详解 | 9 个核心任务的"如何做" + 配置项参考 | 想深入某个功能 |
| **[`CHANGELOG.md`](ai_agent/CHANGELOG.md)** | 后端变更日志 | v0.1.0 ~ v0.4.16 的完整记录(274 个测试的演进) | 升级决策者 |
| **[`INSPECTION_REPORT.md`](ai_agent/INSPECTION_REPORT.md)** | 项目自检报告 | 已实现 / 未实现功能盘点 + 优先级 | 评估成熟度 |
| **[`RELEASE_SUMMARY.md`](ai_agent/RELEASE_SUMMARY.md)** | 发布摘要(DRY-RUN) | v0.1.0 发布过程的产物清单 | 历史参考 |

### 开发者面向文档(写代码时查这 3 个)

| 文档 | 为什么存在 | 有什么用 | 谁该读 |
|---|---|---|---|
| 🔧 **[`agent_middleware.md`](ai_agent/agent_middleware.md)** | 8 个 LangChain Middleware Hook 详解 | 触发时机 / 配置项 / 自定义 Hook 模板 / 何时不该做成 Hook | 🔧 **写 Agent 的开发者** |
| **[`docs/AGENT_ARCHITECTURE_ROADMAP.md`](ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md)** | 架构演进规划 | 七大核心模块的现状盘点 + 分阶段落地计划 | 🏗️ **架构师 / Tech Lead** |
| **[`docs/SPEC_CONTEXT_PERSISTENCE.md`](ai_agent/docs/SPEC_CONTEXT_PERSISTENCE.md)** | 上下文持久化规格说明 | SqliteSaver / MemoryStore 的数据 schema | 二次开发者 |
| **[`docs/STAGE_A_DELIVERY.md`](ai_agent/docs/STAGE_A_DELIVERY.md)** | 阶段 A 交付记录 | 阶段 A(流式中间状态)的交付清单 | 历史参考 |

### 运维面向文档(部署 / 监控 / CI 时查)

| 文档 | 为什么存在 | 有什么用 | 谁该读 |
|---|---|---|---|
| **[`docs/ci-png-cache.md`](ai_agent/docs/ci-png-cache.md)** | CI 镜像缓存策略 | 加速 CI 构建的图片缓存方案 | 🏢 **CI 维护者** |
| **[`docs/web-ui-deploy.md`](ai_agent/docs/web-ui-deploy.md)** | Web UI 部署指南 | 桌面包 / Web 包 / Docker 三种部署方式 | 🏢 **运维** |
| **[`docs/nightly-notify.md`](ai_agent/docs/nightly-notify.md)** | nightly 评测通知机制 | 评测失败时的飞书 / Slack 通知 | 🏢 **DevOps** |
| **[`docs/dashboard-embed.md`](ai_agent/docs/dashboard-embed.md)** | 仪表盘嵌入说明 | 如何把 AI Agent 仪表盘嵌入第三方系统 | 🏢 **集成开发者** |
| **[`docs/auto-archive-approval.md`](ai_agent/docs/auto-archive-approval.md)** | 自动归档审批 | docs/ 旧文档如何归档 | 维护者 |
| **[`docs/archive-acceptance.md`](ai_agent/docs/archive-acceptance.md)** | 归档验收标准 | 历史归档的验收清单 | 维护者 |
| **[`docs/pr-template-required-fields.md`](ai_agent/docs/pr-template-required-fields.md)** | PR 模板必填字段 | 提交 PR 时必须填哪些字段 | 贡献者 |

### 评测 / 测试相关

| 文档 | 为什么存在 | 有什么用 | 谁该读 |
|---|---|---|---|
| **[`evals/README.md`](ai_agent/evals/README.md)** | 评测系统说明 | 274 个测试用例的运行 / 扩展方式 | 测试维护者 |

---

## 🗂️ 第三层:前端子项目文档(web_console/)

> 🎨 `web_console/` 是 React 19 + TypeScript + Vite 5 的前端控制台。

| 文档 | 为什么存在 | 有什么用 | 谁该读 |
|---|---|---|---|
| **[`web_console/README.md`](web_console/README.md)** | 前端项目门面 | 8 大页面说明 / 开发命令 / e2e 测试 | 前端开发者 |
| **[`web_console/QUICKSTART.md`](web_console/QUICKSTART.md)** | 前端快速启动 | `pnpm dev` 跑起来 | 前端新手 |
| **[`web_console/CHANGELOG.md`](web_console/CHANGELOG.md)** | 前端变更日志 | 前端版本演进 | 前端维护者 |
| **[`web_console/.github/RELEASE.md`](web_console/.github/RELEASE.md)** | 前端发布流程 | 如何发布前端 | 前端发布者 |
| **[`web_console/.github/PYPI_PUBLISHING.md`](web_console/.github/PYPI_PUBLISHING.md)** | PyPI 发布指南 | Trusted publishing / API token / OIDC | 发布者 |
| **[`web_console/.github/RELEASE_PIPELINE.md`](web_console/.github/RELEASE_PIPELINE.md)** | 发布流水线 | Release-please / 自动化发布 | 发布者 |
| **[`web_console/.github/PACKAGE_DISTRIBUTION.md`](web_console/.github/PACKAGE_DISTRIBUTION.md)** | 打包分发 | Scoop / Homebrew / PyPI 多渠道 | 发布者 |
| **[`web_console/.github/GITHUB_PAGES_SETUP.md`](web_console/.github/GITHUB_PAGES_SETUP.md)** | GitHub Pages 配置 | 静态站点部署 | 部署者 |
| **[`web_console/.github/GHCR_SETUP.md`](web_console/.github/GHCR_SETUP.md)** | GHCR 配置 | Docker 镜像仓库配置 | 部署者 |
| **[`web_console/.github/SCOOP_BREW_TAP_SETUP.md`](web_console/.github/SCOOP_BREW_TAP_SETUP.md)** | Scoop / Brew 配置 | Windows / macOS 包管理器 | 桌面分发者 |
| **[`web_console/.github/FIRST_RELEASE_RUNBOOK.md`](web_console/.github/FIRST_RELEASE_RUNBOOK.md)** | 首次发布 Runbook | 第一次发布的检查清单 | 首次发布者 |
| **[`web_console/.github/BRANCH_PROTECTION_SETUP.md`](web_console/.github/BRANCH_PROTECTION_SETUP.md)** | 分支保护设置 | main 分支保护规则 | 仓库管理员 |

---

## 🗂️ 第四层:历史归档(tests-archive/)

> 📦 `tests-archive/` 是历史测试和文档的归档,**新用户不需要读**,但**升级决策者**需要看。

| 文档 | 为什么存在 | 用途 |
|---|---|---|
| **[`tests-archive/README.md`](tests-archive/README.md)** | 归档区说明 | 进入归档的规则 |
| **[`tests-archive/CHANGELOG.md`](tests-archive/CHANGELOG.md)** | 归档变更日志 | 历史变更记录 |
| **[`tests-archive/STATUS.md`](tests-archive/STATUS.md)** | 历史状态报告 | 旧版本功能状态 |
| **[`tests-archive/MIGRATION.md`](tests-archive/MIGRATION.md)** | 旧版本迁移指南 | 旧→新版本的数据迁移 |
| **[`tests-archive/ACCEPTANCE.md`](tests-archive/ACCEPTANCE.md)** | 旧验收报告 | 历史验收清单 |
| **[`tests-archive/auto_archive.md`](tests-archive/auto_archive.md)** | 自动归档规则 | 哪些文档会自动归档 |
| **[`tests-archive/TREND.md`](tests-archive/TREND.md)** | 历史趋势数据 | 旧版本的指标趋势 |

> ⚠️ **这些是归档,不是当前文档**。只在排查历史问题时查阅。

---

## 🎯 按使用场景的"剧本路径"

> 不同的目标 → 不同的文档路径。

### 🆕 剧本 1:"我第一次来,想跑起来"

```
1. QUICKSTART.md                    (顶层 5 分钟体验)
2. ai_agent/USAGE.md §1            (后端 5 分钟跑通)
3. web_console/README.md            (前端如何接入)
```

### 🛠️ 剧本 2:"我要把 Agent 接入我的业务"

```
1. ai_agent/README.md               (后端全貌)
2. ai_agent/FEATURES_GUIDE.md       (9 大任务速查)
3. ai_agent/USAGE.md §4             (进阶配置:限流/PII/Token)
4. ai_agent/agent_middleware.md     (8 个 Hook 详解)
```

### 🏢 剧本 3:"我要把 Agent 上生产"

```
1. ai_agent/UPGRADE.md              (升级流程 + 回滚方案)
2. ai_agent/RELEASE_NOTES.md        (当前版本亮点)
3. ai_agent/docs/web-ui-deploy.md   (部署方式)
4. ai_agent/docs/nightly-notify.md  (监控告警)
```

### 🏗️ 剧本 4:"我是架构师,想评估"

```
1. README.md §1.0                  (5 维度对比:vs LangChain/CrewAI/AutoGen)
2. ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md (七大模块盘点)
3. ai_agent/INSPECTION_REPORT.md    (已实现/未实现功能)
4. ai_agent/CHANGELOG.md            (演进速度)
```

### ⬆️ 剧本 5:"我要从 v0.3.x 升到 v0.4.x"

```
1. ai_agent/UPGRADE.md §5           (重大版本迁移)
2. ai_agent/CHANGELOG.md            (v0.3.0 → v0.4.16 变更)
3. ai_agent/docs/SPEC_CONTEXT_PERSISTENCE.md (数据 schema 是否兼容)
```

### 🐛 剧本 6:"Agent 出 bug 了"

```
1. ai_agent/USAGE.md §7              (12 个 FAQ)
2. ai_agent/USAGE.md §8              (故障排查流程图)
3. ai_agent/UPGRADE.md §8            (升级问题对照表)
4. /api/fail-log/summary + /api/events  (运行时诊断)
```

### 📦 剧本 7:"我要发版"

```
1. CHANGELOG.md + ai_agent/CHANGELOG.md  (更新变更日志)
2. ai_agent/RELEASE_NOTES.md              (发布说明)
3. DISTRIBUTION.md                        (顶层分发)
4. web_console/.github/RELEASE.md         (前端发布)
5. web_console/.github/RELEASE_PIPELINE.md (CI 流水线)
```

### 🤝 剧本 8:"我想贡献代码"

```
1. CONTRIBUTING.md                         (顶层贡献指南)
2. ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md (想做什么)
3. .github/PULL_REQUEST_TEMPLATE.md         (PR 模板)
4. ai_agent/docs/pr-template-required-fields.md (必填字段)
```

---

## 📊 文档统计与维护

| 子项目 | 用户面向 | 开发者面向 | 运维面向 | 总计 |
|---|---|---|---|---|
| 顶层根目录 | 3 | 2 | 3 | **8** |
| `ai_agent/` | 8 | 4 | 7 | **19** |
| `web_console/` | 3 | 1 | 9 | **13** |
| `tests-archive/` | 7(归档) | - | - | **7** |
| **总计** | 21 | 7 | 19 | **47** |

### 维护约定

- ✅ **新文档必须加到本入口**,保持单一入口原则
- ✅ **过时文档移到 `tests-archive/`**,而不是删除
- ✅ **每个文档必须有"为什么存在"的说明**,而非只是文件清单
- ✅ **跨文档链接用相对路径**(`ai_agent/USAGE.md` 而非绝对 URL)

---

## 🗺️ 文档关系图(从属关系)

```
README.md (本仓库)
├── ai_agent/README.md            ── 子门面
│   ├── USAGE.md                  ── 新手指引
│   │   ├── 引用 → agent_middleware.md §3.5
│   │   └── 引用 → FEATURES_GUIDE.md
│   ├── UPGRADE.md                ── 升级
│   │   └── 引用 → CHANGELOG.md (v0.4.3)
│   ├── RELEASE_NOTES.md          ── 最新发布
│   │   └── 引用 → CHANGELOG.md (本版本)
│   ├── agent_middleware.md       ── 技术细节
│   ├── FEATURES_GUIDE.md         ── 功能详解
│   ├── CHANGELOG.md              ── 变更日志
│   ├── INSPECTION_REPORT.md      ── 自检
│   ├── RELEASE_SUMMARY.md        ── 历史发布
│   └── docs/
│       ├── AGENT_ARCHITECTURE_ROADMAP.md  ── 架构
│       ├── SPEC_CONTEXT_PERSISTENCE.md    ── 数据 schema
│       ├── STAGE_A_DELIVERY.md            ── 历史交付
│       ├── ci-png-cache.md                ── CI
│       ├── web-ui-deploy.md               ── 部署
│       ├── nightly-notify.md              ── 监控
│       ├── dashboard-embed.md             ── 集成
│       ├── auto-archive-approval.md       ── 归档规则
│       ├── archive-acceptance.md          ── 归档验收
│       └── pr-template-required-fields.md ── PR 规范
│
├── web_console/README.md         ── 前端门面
│   ├── QUICKSTART.md
│   ├── CHANGELOG.md
│   └── .github/*.md              ── 发布 / CI / 分发
│
├── docs/                          ── 顶层 API / 目录结构
├── .github/                       ── 顶层 PR 模板 / 安全策略
├── CHANGELOG.md                   ── 顶层变更
├── QUICKSTART.md                  ── 顶层 5 分钟
├── CONTRIBUTING.md                ── 贡献
├── DISTRIBUTION.md                ── 分发
└── tests-archive/                 ── 历史归档
    └── *.md
```

---

## 📜 文档版本管理

| 文档 | 同步频率 | 维护责任人 |
|---|---|---|
| `README.md` / `ai_agent/README.md` | 每个 Release | 核心团队 |
| `CHANGELOG.md` | 每次 PR | 自动生成 |
| `USAGE.md` / `UPGRADE.md` / `RELEASE_NOTES.md` | 每个 Release | 核心团队 |
| `agent_middleware.md` | Hook 变更时 | Middleware 维护者 |
| `docs/*.md` | 相关功能变更时 | 各模块负责人 |
| `web_console/*.md` | 前端 Release | 前端团队 |
| `tests-archive/*.md` | 归档时(只读) | - |

---

## 🎁 最佳实践:写新文档时

1. ✅ **先回答"为什么存在"** — 不用这个文档会出什么问题?
2. ✅ **明确"谁该读"** — 新手?开发者?运维?
3. ✅ **加到本入口** — 保持单一入口
4. ✅ **交叉引用** — 用相对路径链接相关文档
5. ✅ **加 TL;DR** — 60 秒能看完的精华
6. ✅ **加"读完检测"** — 让读者自测是否掌握

---

## 🆘 找不到答案?

按顺序尝试:

1. 🔍 在本入口用 `Ctrl+F` 搜关键词
2. 🤖 Agent 内部:`/api/help` 端点
3. 🐛 GitHub Issues:https://github.com/colbertlee/langChain_langGraph/issues
4. 💬 GitHub Discussions:https://github.com/colbertlee/langChain_langGraph/discussions
5. 📧 联系维护者(见 README)

---

> 📌 **下一步**:看完本文档后,根据你的角色(剧本 1~8)跳到对应路径。
> 🎉 **让文档成为你的朋友,而不是障碍**。
