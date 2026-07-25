# 完整可分发包

本目录存放**完整、可独立运行**的程序包，整个文件夹直接拷到任何 Windows / Linux 电脑上即可双击/命令行运行。

```
package/
├─ windows/              完整 Windows 程序（双击 install.bat → run.bat）
└─ linux/                完整 Linux 程序（./install.sh → ./run.sh）
```

## 完整目录结构（以 windows/ 为例，linux/ 对称）

```
windows/
├─ ai-agent.exe         ← PyInstaller 编译的 110 MB 主程序（自带 Python 运行时）
├─ _internal/           ← PyInstaller 运行时（LangChain 1.x、langgraph、mcp、chroma、numpy…）
├─ install.bat          首次配置：生成 .env、建目录
├─ run.bat              启动 CLI（双击）
├─ run-web.bat          启动 Web 服务（需重打 app.py 入口）
├─ .env.example         LLM API Key 模板
├─ mcp_config.json      MCP 工具配置
├─ knowledge_base/      内置知识库
├─ prompts/             Prompt 模板
├─ README.txt           用户使用说明
└─ smoke_*.ps1          开发者 smoke 测试
```

## 用户使用（拷到任何电脑后）

### Windows
1. 拷贝整个 `windows/` 目录到目标电脑
2. 双击 `install.bat` → 记事本打开 `.env` → 填入 `LLM_API_KEY=...`
3. 双击 `run.bat` → 启动 CLI

### Linux
```bash
cd linux/
chmod +x ai-agent install.sh run.sh
./install.sh
nano .env      # 填入 LLM_API_KEY
./run.sh
```

## 开发者：重新打包

```powershell
# Windows 上：清理 → 打包 → 拷贝到 package\windows → 压缩
cd ai_agent
Remove-Item -Recurse -Force build, dist
pyinstaller ai_agent.spec --clean --noconfirm
Copy-Item -Recurse -Force dist\ai-agent\* package\windows\
.\package_dist.ps1
# → 生成 dist\ai-agent-windows.zip
```

```bash
# Linux 上 / Docker
cd ai_agent
pyinstaller ai_agent.spec --clean --noconfirm
cp -r dist/ai-agent/. package/linux/
chmod +x package/linux/ai-agent package/linux/*.sh
tar -czf dist/ai-agent-linux.tar.gz -C package/linux .
```

## 自动化 CI

`.github/workflows/release-build.yml` 会用 GitHub Actions 矩阵
（windows-latest / ubuntu-latest / macos-latest）自动构建三端包，
推 `v*.*.*` tag 即生成 GitHub Release。

## Linux 二进制说明

`ai-agent` 二进制是平台相关的（Windows exe 不能在 Linux 跑，反之亦然）。
本仓库的 Windows 包已包含 `ai-agent.exe`；Linux 包里的 `ai-agent`
需要由 CI / Linux 主机 / Docker 自动生成。详见 `package/linux/BUILD_ON_LINUX.md`。
