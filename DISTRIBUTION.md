# 分发与安装总览 · Distribution

> AI Agent 平台提供 7 种分发/安装渠道。每种渠道面向不同用户,文档独立但口径一致。
> 适用对象、产物大小、签名/校验方式均在此汇总,详细步骤请跳转到对应子文档。

## 1. 渠道一览

| 渠道 | 平台 | 适合 | 产物 | 用户命令 |
|---|---|---|---|---|
| **源码运行** | Win / Linux / macOS | 开发者 | — | `git clone …` + `pip install -r requirements.txt` + `python app.py` |
| **桌面二进制** | Win / Linux / macOS | 终端用户 | PyInstaller 单文件 + `_internal/` | `install.bat` / `install.sh` → `run.bat` / `run.sh` |
| **Docker** | 任意 | 运维 / 私有部署 | GHCR `ai-agent-console:latest` | `docker compose up -d` |
| **PyPI** | 任意 | Python 开发者 | `ai-agent` wheel | `pip install ai-agent` |
| **Scoop** | Windows | CLI 玩家 | `scoop bucket add colbertlee/ai-agent` | `scoop install ai-agent` |
| **Homebrew** | macOS / Linux | CLI 玩家 | `colbertlee/tap/ai-agent` | `brew install ai-agent` |
| **GitHub Release** | 任意 | 高级用户 | `.zip` / `.tar.gz` / `.exe` / checksums | 浏览器下载 |

## 2. 桌面二进制(Windows)

```cmd
:: 解压 ai-agent-windows.zip 到任意目录
cd ai-agent-windows
install.bat        :: 创建 .env 与目录
notepad .env       :: 填入 OPENAI_API_KEY=...
run.bat            :: 启动 CLI
run-web.bat        :: 启动 Web 服务(浏览器打开 http://localhost:8000)
```
- 包大小:压缩 ~470 MB,解压 ~1.16 GB
- 含全部 Python 运行时 + LangChain/LangGraph/MCP/Chroma
- 不需要预装 Python
- 详细文档:[ai_agent/package/windows/README.txt](ai_agent/package/windows/README.txt)

## 3. 桌面二进制(Linux)

```bash
tar -xzf ai-agent-linux-x64.tar.gz
cd ai-agent-linux
chmod +x ai-agent install.sh run.sh
./install.sh
nano .env          # 设置 LLM_API_KEY
./run.sh           # CLI
./run-web.sh       # Web
```
- 必须在 Linux x64 上构建(或用 Docker 构建)。详见 [ai_agent/package/linux/BUILD_ON_LINUX.md](ai_agent/package/linux/BUILD_ON_LINUX.md)
- 详细文档:[ai_agent/package/linux/README.txt](ai_agent/package/linux/README.txt)

## 4. 桌面二进制(macOS)

```bash
tar -xzf ai-agent-macos-arm64.tar.gz    # Apple Silicon
# 或
tar -xzf ai-agent-macos-x64.tar.gz      # Intel

cd ai-agent-macos
chmod +x ai-agent install.sh run.sh
xattr -dr com.apple.quarantine ai-agent   # 移除隔离属性(首次)
./install.sh
nano .env          # 设置 LLM_API_KEY
./run.sh
```
- macOS Gatekeeper 可能拦截未签名二进制 → 系统设置 → 隐私与安全性 → 仍要打开
- Apple Silicon 与 Intel 分开构建
- 与 Linux 包使用同一份 `install.sh` / `run.sh`

## 5. Docker

```bash
# 仓库根目录
cp .env.example .env          # 填写 LLM_API_KEY
docker compose up -d --build
# 浏览器打开 http://localhost:8000
```
- 多阶段:`web_console/Dockerfile` 先 Node 20 构建前端,再嵌入 python:3.11-slim
- 内置 healthcheck `/api/health`
- 数据卷:将 `ai_agent_data` / `ai_agent_uploads` 挂出
- 详细:[web_console/Dockerfile](web_console/Dockerfile) + [docker-compose.yml](docker-compose.yml)

## 6. PyPI

```bash
pip install ai-agent
ai-agent            # 启动 Web
ai-agent-test       # 跑测试
ai-agent-lint       # ruff check
```
- 元数据:[ai_agent/pyproject.toml](ai_agent/pyproject.toml)
- 发布:GitHub Actions `release.yml` 通过 OIDC + PEP 740 provenance 自动发版
- 详细:[web_console/.github/PYPI_PUBLISHING.md](web_console/.github/PYPI_PUBLISHING.md)

## 7. Scoop (Windows)

```powershell
scoop bucket add colbertlee https://github.com/colbertlee/scoop-bucket
scoop install ai-agent
```
- Manifest:[ai_agent/scoop-bucket-ai-agent.json](ai_agent/scoop-bucket-ai-agent.json)
- 自动更新 scoop → 新版本自动通知

## 8. Homebrew (macOS / Linux)

```bash
brew tap colbertlee/tap
brew install ai-agent
```
- Formula:[ai_agent/homebrew-tap-ai-agent.rb](ai_agent/homebrew-tap-ai-agent.rb)

## 9. GitHub Release

```bash
# 下载 release asset
gh release download v2.0.0 --repo colbertlee/langChain_langGraph
shasum -a 256 ai-agent-windows.zip     # 校验
```
- 由 `release.yml` 在 push tag `v*.*.*` 触发
- 包含 Windows / Linux / macOS 三平台 zip + checksums + 桌面二进制包

## 10. 卸载(Uninstall)

不同渠道的卸载步骤不同,请按你安装的渠道选择。

### 10.1 源码运行
```bash
# 删除项目目录
rm -rf langChain_langGraph    # Linux/macOS
# Windows: 直接删除文件夹
# Python 依赖是虚拟环境的,直接删除 .venv/
# 全局 pip 装的:pip uninstall ai-agent
```

### 10.2 桌面二进制
**Windows**:
1. 退出 `run.bat` / `run-web.bat`(关闭 cmd 窗口)
2. 删除整个解压目录(如 `D:\apps\ai-agent-windows`)
3. 用户级配置 `C:\Users\<you>\.ai-agent\`(如有)→ 手动删除
4. 检查任务管理器有无残留 `ai-agent.exe` 进程

**Linux**:
```bash
# 1. 退出当前进程
pkill -f ai-agent
# 2. 删除安装目录
rm -rf ~/ai-agent-linux
# 3. 删除用户级配置
rm -rf ~/.ai-agent/
```

**macOS**:
```bash
pkill -f ai-agent
rm -rf ~/Applications/ai-agent-macos
rm -rf ~/.ai-agent/
```

### 10.3 Docker
```bash
# 停止并删除容器 + 默认网络
docker compose down

# ⚠️ 加上 -v 会同时删除数据卷,意味着 context_memory.db / uploads / chroma_db 全部清空
docker compose down -v

# 删除镜像
docker rmi ghcr.io/colbertlee/ai-agent-console:latest
# 或本地 tag
docker rmi ai-agent-console:latest

# 删除所有残留数据卷(可选)
docker volume ls | grep ai_agent
docker volume rm <volume_name>
```

### 10.4 PyPI
```bash
pip uninstall ai-agent
# 删除用户级配置
rm -rf ~/.ai-agent/         # Linux/macOS
rmdir /s /q %USERPROFILE%\.ai-agent   # Windows
```

### 10.5 Scoop
```powershell
scoop uninstall ai-agent
# scoop 不会自动清理用户级配置,手动删:
Remove-Item -Recurse $env:USERPROFILE\.ai-agent
```

### 10.6 Homebrew
```bash
brew uninstall ai-agent
rm -rf ~/.ai-agent/
```

### 10.7 GitHub Release
- 直接删除下载的 `.zip` / `.exe` / `.tar.gz` 文件
- 如已解压,见 §10.2 桌面二进制卸载步骤
- GitHub 上的 Release 资产本身无法删除(除非删整个 release),但不影响你的本地环境

### 10.8 卸载后还能保留什么
**可保留**(用于下次安装复用):
- `.env`(含 API Key)→ 复制到新环境
- `uploads/`(上传的文档)
- `chroma_db/`(RAG 索引)
- `context_memory.db`(对话历史)

**必须删除**(隐私 / 安全):
- API Key(从 `.env` 取出后单独保存)
- 任何包含 API Key 的日志副本

---

## 11. 渠道选择建议

| 你是… | 推荐渠道 |
|---|---|
| 想贡献代码 | 源码运行 |
| 想给自己团队装桌面客户端 | 桌面二进制 |
| 想在服务器跑 | Docker |
| 想塞进 Python 项目 | PyPI |
| 想 `scoop update` 自动升级 | Scoop |
| 想 `brew upgrade` 自动升级 | Homebrew |
| 想人工下载校验 | GitHub Release |

---

## 12. 校验与签名

| 渠道 | 校验方式 |
|---|---|
| PyPI | PEP 740 attestation + OIDC trusted publisher |
| Docker GHCR | Sigstore cosign + provenance |
| GitHub Release | SHA-256SUMS 文件(由 release workflow 生成) |
| Scoop / Homebrew | manifest 内置 `sha256` 字段 |
| 桌面二进制 | 内置 SHA-256 校验脚本 |

---

## 13. 相关文档索引

| 主题 | 文档 |
|---|---|
| PyPI 发版 | [web_console/.github/PYPI_PUBLISHING.md](web_console/.github/PYPI_PUBLISHING.md) |
| GHCR | [web_console/.github/GHCR_SETUP.md](web_console/.github/GHCR_SETUP.md) |
| Tap (Scoop/Brew) | [web_console/.github/SCOOP_BREW_TAP_SETUP.md](web_console/.github/SCOOP_BREW_TAP_SETUP.md) |
| 桌面二进制分发 | [ai_agent/package/README.md](ai_agent/package/README.md) |
| Windows 包 | [ai_agent/package/windows/README.txt](ai_agent/package/windows/README.txt) |
| Linux 包 | [ai_agent/package/linux/README.txt](ai_agent/package/linux/README.txt) |
| Linux 构建 | [ai_agent/package/linux/BUILD_ON_LINUX.md](ai_agent/package/linux/BUILD_ON_LINUX.md) |
| 桌面三平台 CI | [ai_agent/.github/workflows/release-build.yml](ai_agent/.github/workflows/release-build.yml) |
| 完整发布流水线 | [web_console/.github/RELEASE_PIPELINE.md](web_console/.github/RELEASE_PIPELINE.md) |
| 首次发版 runbook | [web_console/.github/FIRST_RELEASE_RUNBOOK.md](web_console/.github/FIRST_RELEASE_RUNBOOK.md) |
| 总览 | [README.md](README.md) |