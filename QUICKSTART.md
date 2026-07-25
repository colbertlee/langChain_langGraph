# 快速开始 · Quickstart

> 5 分钟把 AI Agent 平台跑起来。详细架构与配置说明见 [README.md](README.md)。

## 0. 前置条件

| 依赖 | 版本 | 用途 |
|---|---|---|
| Python | 3.11+ (推荐 3.12) | 后端运行时 |
| Node.js | 20+ | 仅当使用 React 控制台时需要 |
| Git | 任意 | 拉取代码 |
| Docker | 24+ | 仅当使用容器模式时需要 |

## 0.5 · 30 秒无 Key 试玩(新用户首选)

还没拿到 LLM API Key?**不用卡在这一步**。先跑离线测试看到全栈跑通,再决定要不要接 Key。

```bash
cd ai_agent
pip install -r requirements.txt
pytest tests/test_basic.py tests/test_agent_run.py tests/test_app_e2e.py -q
# 期望: ~40 passed,全离线,无需任何 API Key
```

更多离线用例 → [ai_agent/tests/](ai_agent/tests/) 全量套件 ~96 用例;或运行 `python main.py` 进 REPL,Agent 会以 placeholder 模式启动,你可以看到 CLI 框架 / 工具注册 / 记忆初始化全部就绪,只是回答会提示 "no LLM key configured"。

---

## 1. 拉代码

```bash
git clone https://github.com/colbertlee/langChain_langGraph.git
cd langChain_langGraph
```

## 2. 启动后端(必须)

```bash
cd ai_agent
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
# 编辑 .env,至少填一个 LLM_API_KEY(见 README §4.2)
python app.py
# 监听 http://localhost:8000
```

验证:
```bash
curl http://localhost:8000/api/health
# 期望: {"status":"ok"}
```

## 3. 选择前端

### 选项 A · 单文件 HTML 主界面(最轻量,推荐)
```bash
# 另一终端
cd ai_agent/web
python -m http.server 8765
# 浏览器打开 http://localhost:8765/
```
5 个 tab:设置 / 工具 / 记忆 / 计划 / 运维/观测。

### 选项 B · React 控制台(新,功能逐步对齐主界面)
```bash
cd web_console
npm ci
npm run dev
# 浏览器打开 http://localhost:5173
```
8 个路由:`/`、`/agents`、`/approval`、`/observability`、`/tools`、`/settings`、`/prompts`、`/memory`。

### 选项 C · Docker 一键(前后端一体)
```bash
# 仓库根目录
cp .env.example .env          # 填写 LLM_API_KEY
docker compose up -d --build
# 浏览器打开 http://localhost:8000
```

## 4. CLI(最轻)

```bash
cd ai_agent
python main.py
# REPL: "现在几点了?" / "计算 2+3*4" / "exit"
```

## 5. 跑测试

```bash
# 后端
cd ai_agent
py -3.11 -m pytest tests/ -v          # 期望 96+ passed

# 前端
cd ../web_console
npm test                               # 期望 vitest 全部通过

# 包冒烟(可选,验证 PyInstaller 产物)
cd ../ai_agent
./test_all.ps1                         # Windows
./test_package.sh                      # Linux
```

## 6. 端口一览

| 端口 | 服务 | 命令 |
|---|---|---|
| 8000 | 后端 FastAPI | `python app.py` |
| 8765 | 单文件 HTML 主界面 | `python -m http.server 8765` |
| 5173 | React 控制台 dev | `npm run dev` |
| 8000 | Docker 模式(同后端) | `docker compose up -d` |

## 7. 下一步

- 想自定义 LLM Provider / 工具 / Prompt?→ [README.md §5 开发与自定义](README.md)
- 想打包成 Windows / Linux / macOS 桌面二进制?→ [README.md §6 部署与运维](README.md) + [ai_agent/package/README.md](ai_agent/package/README.md)
- 想发版到 PyPI / GHCR / Scoop / Homebrew?→ [web_console/.github/PACKAGE_DISTRIBUTION.md](web_console/.github/PACKAGE_DISTRIBUTION.md)

## 8. 故障排除

| 现象 | 排查 |
|---|---|
| `OPENAI_API_KEY not set` | 在 `.env` 填入真 Key,或 `python main.py` 内置 set-key |
| 端口被占 | `PORT=9000 python app.py` |
| 全部 Provider 不可用 | 五层容错栈会触发降级;查看 `/api/fail-log/summary` |
| 桌面二进制启动失败 | 详见 [ai_agent/package/windows/README.txt](ai_agent/package/windows/README.txt) / [ai_agent/package/linux/README.txt](ai_agent/package/linux/README.txt) |