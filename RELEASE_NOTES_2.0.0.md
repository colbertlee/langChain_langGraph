# 🚀 Release Notes · v2.0.0 "Gitee Official"

> **发布日期**:2026-08-02 · **代号**:"Gitee Official" · **完整变更**:[`CHANGELOG.md`](CHANGELOG.md) · **升级指南**:[`UPGRADE.md`](UPGRADE.md)
>
> 本次为面向 Gitee 社区的**正式版发布**。自此版本起,推荐国内用户从 Gitee 仓库直接拉取、安装、二进制分发。

---

## 📋 文档元信息

| 项 | 值 |
|---|---|
| 🎯 **目标读者** | 现有用户 / 升级决策者 / 新用户 |
| ⏱️ **预计阅读** | 8 分钟(决策用) / 3 分钟(只看 TL;DR) |
| 📊 **难度评级** | ⭐⭐ |
| 🏷️ **版本类型** | Major Release(向下兼容数据,默认监听地址收紧) |
| ⚠️ **风险等级** | 🟢 低 |

---

## 🎯 TL;DR(60 秒决策版)

> 🟢 **正式版已经发布到 Gitee**,一键安装命令已就绪。

```bash
# 方案 A · 桌面二进制(Windows / Linux / macOS):见下方 §1
# 方案 B · PyPI:pip install ai-agent==2.0.0
# 方案 C · 源码:git clone https://gitee.com/colbertlee/langChain_langGraph.git
```

**v2.0.0 主要看点**:
1. 🇨🇳 **Gitee 主源分发** — 国内用户从 Gitee 拉取,告别 GitHub 抽风
2. 📦 **三平台桌面包** — Windows / Linux / macOS,开箱即用,免装 Python
3. 🔐 **PEP 740 + cosign + SHA256** — 全链路签名/校验
4. 🧠 **Harness 评测框架** — PR1~17 评测已稳定落地(94+ 用例)
5. 🩺 **Doctor / Diagnose / Webhook** — 全新可观测与告警中心

---

## 📖 阅读路径

| 你是谁? | 看哪些章节 |
|---|---|
| ⏱️ **赶时间** | TL;DR → §1 安装 |
| 🇨🇳 **国内用户** | §1 + §4 Gitee 安装 |
| 🔬 **想了解技术** | §2 亮点 → §6 完整更新清单 |
| 🏢 **生产决策** | §3 兼容性 → §7 已知问题 → §9 升级清单 |
| 🔧 **想立刻启用新功能** | §5 一行代码启用 |

---

## 1. 安装 / 升级 ⭐

### 1.1 国内推荐 · Gitee 源码 / 桌面包

```bash
# 拉源码
git clone https://gitee.com/colbertlee/langChain_langGraph.git
cd langChain_langGraph
pip install -r ai_agent/requirements.txt
cd ai_agent && python app.py          # 监听 http://localhost:8000
```

桌面包资产见本 Release 页"Assets"区:
- `ai-agent-windows.zip`(≈470 MB)
- `ai-agent-linux-x64.tar.gz`(≈500 MB)
- `ai-agent-macos-arm64.tar.gz` / `ai-agent-macos-x64.tar.gz`(由 GitHub Actions 产出后同步)
- `SHA256SUMS`(三包校验)

### 1.2 PyPI(全球通用)

```bash
pip install ai-agent==2.0.0
ai-agent             # 启动 Web(127.0.0.1:8000)
ai-agent-doctor      # 健康检查
ai-agent-test        # 跑 pytest
```

### 1.3 Docker

```bash
docker pull ghcr.io/colbertlee/ai-agent-console:2.0.0
docker pull ghcr.io/colbertlee/ai-agent-console:latest
```

### 1.4 从 v1.x 升级

```bash
# 源码
git pull origin main
pip install -r ai_agent/requirements.txt --upgrade

# PyPI
pip install --upgrade ai-agent

# Docker
docker pull ghcr.io/colbertlee/ai-agent-console:latest
```

> 💡 详细步骤见 [`UPGRADE.md`](UPGRADE.md)。

---

## 2. 本版本亮点 ⭐⭐⭐

### 🎯 亮点 1:正式版登陆 Gitee — 国内用户首选

> 🇨🇳 **告别 GitHub 抽风**

- 仓库镜像:[https://gitee.com/colbertlee/langChain_langGraph](https://gitee.com/colbertlee/langChain_langGraph)
- 同步频率:push 到 GitHub 后由 Gitee 自动同步,延迟 ≤ 60s
- Tag / Release:本 v2.0.0 同时在 Gitee 与 GitHub 创建
- 桌面包资产优先托管在 Gitee Release,国内下载速度 5–10 MB/s

### 🎯 亮点 2:Harness 评测框架稳定落地

> 🧪 **PR1~17 共 94+ 评测用例** 已合入主分支,覆盖路由 / 安全 / 算子 / 计划 / 记忆 / 多 Agent / 端到端。

### 🎯 亮点 3:Doctor / Diagnose / Webhook

> 🩺 **可观测中心**:新增 `ai-agent-doctor` 命令与 `/api/diagnose` 端点,以及 ChatOps Webhook(支持 Slack / 飞书)。

### 🎯 亮点 4:WebHook & Doctor ChatOps

> 🔔 **告警分级 + 静默窗口 + 失败回放**,直接对接企业内部 IM。

### 🎯 亮点 5:RAG 加载器拓展 + MiniMax MCP 接入

> 🧩 **文档/网页/表格** 三类加载器,MiniMax 官方 MCP 标准化接入(详见 [.env.example](ai_agent/.env.example))。

---

## 3. 升级兼容性 ⭐⭐⭐

> ✅ **数据完全兼容** · 旧 `.db` / `chroma_db/` / `uploads/` 直接复用。

### 3.1 兼容性矩阵

| 从哪个版本 | 兼容性 | 升级难度 | 是否需改代码 |
|---|---|---|---|
| **v1.x → v2.0.0** | ✅ 数据兼容 | 🟢 1 分钟 | ⚠️ 仅一行:`HOST=0.0.0.0` |
| v0.4.x → v2.0.0 | ✅ 兼容 | 🟡 5 分钟 | ⚠️ 入口 `app.py`,日志级别 `WARNING` |

### 3.2 兼容性保障机制

- ✅ 默认监听 `127.0.0.1:8000`(对外暴露需 `HOST=0.0.0.0`)
- ✅ 日志默认 `WARNING` 级(`LOG_LEVEL=INFO` 调高)
- ✅ 数据 schema 跨版本无需迁移
- ✅ 274+ pytest 用例守护

---

## 4. Gitee 安装指南(国内用户)

### 4.1 桌面包(最省心)

```powershell
:: Windows
Invoke-WebRequest "https://gitee.com/colbertlee/langChain_langGraph/releases/download/v2.0.0/ai-agent-windows.zip" -OutFile ai-agent-windows.zip
Expand-Archive ai-agent-windows.zip
cd ai-agent-windows
.\install.bat
notepad .env         # 填 LLM_API_KEY
.\run.bat            # CLI 模式
.\run-web.bat        # Web 模式
```

```bash
# Linux / WSL
wget https://gitee.com/colbertlee/langChain_langGraph/releases/download/v2.0.0/ai-agent-linux-x64.tar.gz
tar -xzf ai-agent-linux-x64.tar.gz
cd ai-agent-linux
chmod +x install.sh run.sh ai-agent
./install.sh
nano .env            # 填 LLM_API_KEY
./run.sh             # CLI
./run-web.sh         # Web
```

### 4.2 校验(SHA256)

```bash
# 下载 SHA256SUMS,与本地 .zip / .tar.gz 校验
sha256sum -c SHA256SUMS
# 全部 OK 表示未被篡改
```

### 4.3 镜像加速拉源码

```bash
# 如果 gitee.com 也慢,使用 ghfast.top 中转
git clone https://ghfast.top/https://github.com/colbertlee/langChain_langGraph
```

---

## 5. 一行代码启用新功能 ⭐

```python
# 1. Doctor · 健康自检
from doctor import run_diagnose
print(run_diagnose().summary())

# 2. ChatOps Webhook
from doctor_chatops import notify
notify(level="info", title="Agent 启动", message="ready")

# 3. MiniMax MCP
# 已在 .env.example 配好 MINIMAX_API_KEY/MINIMAX_API_HOST,启动即生效

# 4. RAG 加载器
from rag import RAGModule
rag = RAGModule()
rag.load_url("https://example.com/docs")      # 网页
rag.load_table("./data.xlsx")                  # 表格
```

---

## 6. 完整更新清单

### ✨ Added
- 🇨🇳 Gitee 主源镜像同步
- 🧪 Harness 评测框架 PR1~17 稳定落地
- 🩺 `ai-agent-doctor` 命令 + `/api/diagnose` 端点
- 🔔 Doctor ChatOps · Webhook(支持 Slack / 飞书)
- 🧩 RAG 加载器:URL / Table
- 🤖 MiniMax MCP 官方接入

### 🔧 Changed
- 默认监听 `127.0.0.1:8000`(对外暴露需 `HOST=0.0.0.0`)
- 默认日志级别 → `WARNING`

### 🐛 Fixed
- 修复若干 harness 评测边界 case
- 修复 doctor endpoint 在 windows 长路径下超时
- 修复 Webhook payload 中文编码问题

---

## 7. 已知问题

### 7.1 无新增已知问题

### 7.2 遗留(适用于所有 v2.x)
- ⚠️ macOS arm64 / x64 二进制需要在 macOS runner 上构建(本包为多平台同步,首发仅含 Win/Linux)
- ⚠️ PyPI Trusted Publishing 需要在 PyPI 项目页配置"Pending Publisher"

---

## 8. 升级后验证清单 ✅

```bash
# 8.1 健康检查
curl http://localhost:8000/api/health          # {"status":"ok"}

# 8.2 版本号
curl http://localhost:8000/api/version         # 包含 "2.0.0"

# 8.3 Doctor
ai-agent-doctor                                  # 输出 PASS/WARN/FAIL

# 8.4 Pytest
pytest ai_agent/tests/ -v                        # 96+ passed
```

---

## 9. 升级清单(可打印) ✅

### 升级前
- [ ] 已备份 `.env` / `*.db` / `chroma_db/` / `uploads/`
- [ ] 已确认监听端口冲突(8000)

### 升级中
- [ ] 拉取 Gitee 最新源码 / `pip install --upgrade ai-agent`
- [ ] 健康检查 `/api/health` 返回 ok

### 升级后
- [ ] 版本号确认 2.0.0
- [ ] Doctor 自检全部 PASS
- [ ] 测试用例 96+ 通过

---

## 10. 反馈渠道

| 渠道 | 用途 |
|---|---|
| 🇨🇳 [Gitee Issues](https://gitee.com/colbertlee/langChain_langGraph/issues) | Bug / Feature / Question |
| 🐛 [GitHub Issues](https://github.com/colbertlee/langChain_langGraph/issues) | 同步镜像 |
| 💬 Discussions | 使用讨论 |
| 🔧 Pull Requests | 代码贡献 |

---

## 📚 相关文档

| 文档 | 用途 |
|---|---|
| [`README.md`](README.md) | 项目总览 |
| [`QUICKSTART.md`](QUICKSTART.md) | 5 分钟起步 |
| [`DISTRIBUTION.md`](DISTRIBUTION.md) | 7 种分发渠道 |
| [`UPGRADE.md`](UPGRADE.md) | 升级指南 |
| [`FEATURES_GUIDE.md`](ai_agent/FEATURES_GUIDE.md) | 功能详解 |
| [`CHANGELOG.md`](CHANGELOG.md) | 完整变更日志 |
| [`docs/TECHNICAL_ARCHITECTURE.md`](docs/TECHNICAL_ARCHITECTURE.md) | 技术架构 |
| [`ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md`](ai_agent/docs/AGENT_ARCHITECTURE_ROADMAP.md) | 架构路线图 |

---

## 📜 许可

MIT License — 详见 `LICENSE`。

---

> 🎉 **v2.0.0 正式版已发布到 Gitee!** 欢迎给项目一个 ⭐ Star,有任何问题在 Gitee Issue 区提问,社区会尽快回复。