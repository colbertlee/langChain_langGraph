# Web Console · AI Agent 控制台

> React 19 + Vite 5 + TypeScript 5 + Tailwind 3 + Zustand 4 + @assistant-ui/react 0.14
> 单页应用(SPA),为 LangChain × LangGraph AI Agent 提供桌面级可视化操作台。

---

## 1. 项目概览

`web_console/` 是 AI Agent 平台的**前端控制台**,与 `../ai_agent` 后端通过 REST + SSE 协作。提供 8 个核心模块:聊天、Agent 管理、审批中心、可观测性、工具广场、设置、Prompt 库、记忆查看;并使用 `assistant-ui` 提供流式对话、工具调用可视化、消息附件、Mermaid/代码块高亮。

### 技术栈
| 类别 | 选型 |
|---|---|
| 框架 | React 19.2 + react-router-dom 6.26 |
| 构建 | Vite 5.4 + TypeScript 5.6 |
| 样式 | Tailwind 3.4 + clsx + framer-motion 11 |
| 状态 | Zustand 4.5 (`chatStore` / `uiStore`) |
| 对话 | @assistant-ui/react 0.14.27 + react-markdown 9 |
| 代码高亮 | react-syntax-highlighter 15 |
| 图标 | lucide-react 0.453 |
| 测试 | vitest 4.1 + @testing-library/react 16 + Playwright 1.61 |

### 目录结构
```
web_console/
├─ src/
│  ├─ components/
│  │  ├─ assistant-ui/thread.tsx       # 会话流(assistant-ui 适配层)
│  │  ├─ chat/SessionList.tsx          # 会话侧栏
│  │  └─ layout/{AppShell,Sidebar,TopBar}.tsx
│  ├─ hooks/useAgentThreadListRuntime.ts # 会话列表运行时桥接
│  ├─ lib/{api,utils,syntaxLanguages,attachmentAdapter,threadListAdapter}.ts
│  ├─ pages/                          # 路由页(Chat/Agents/Approval/...)
│  ├─ stores/{chatStore,uiStore}.ts    # 全局状态
│  ├─ styles/globals.css              # Tailwind base + 自定义令牌
│  ├─ types/api.ts
│  ├─ App.tsx                         # 路由 + 健康检查
│  └─ main.tsx
├─ e2e/{app,visual}.spec.ts           # Playwright 端到端
├─ scripts/                           # 分发仓库脚手架、基线图生成
├─ .github/workflows/                 # CI / Docker / Release
├─ Dockerfile                         # 多阶段:Node 构建前端 → Python 启动后端
├─ tailwind.config.js / postcss.config.js / vite.config.ts
├─ playwright.config.ts / vitest.config.ts
└─ package.json
```

---

## 2. 快速开始

### 2.1 本地开发(联动 ai_agent 后端)
```bash
cd web_console
npm ci
npm run dev                 # http://localhost:5173 ,自动代理 /api -> :8000
```
> 默认 Vite dev server 会把 `/api` 代理到 `http://127.0.0.1:8000`(见 `vite.config.ts`)。

### 2.2 后端必须先运行
```bash
# 另一终端
cd ../ai_agent
pip install -r requirements.txt
cp .env.example .env        # 填入至少一个 LLM_API_KEY
python -m uvicorn ai_agent.web_ui:app --reload --port 8000
```

### 2.3 仅前端(无后端)
```bash
npm run dev
# UI 仍可加载,顶部状态指示灯会变红;Chat 页可输入但请求会失败提示。
```

### 2.4 构建生产产物
```bash
npm run build               # 输出 dist/ ,由 Dockerfile frontend-builder 阶段消费
npm run preview             # 静态预览
```

### 2.5 单元 / E2E 测试
```bash
npm test                    # vitest 单元测试
npm run test:coverage       # + coverage
npm run e2e:install         # 安装 chromium
npm run e2e                 # Playwright 端到端
npm run e2e:update          # 更新视觉基线
```

---

## 3. Agent 设计与架构

### 3.1 路由树
| Path | 组件 | 作用 |
|---|---|---|
| `/` | `Chat` | 流式对话、附件、工具调用、消息回溯 |
| `/agents` | `Agents` | 多 Agent 列表 / 启动 / 编排模式 |
| `/approval` | `Approval` | HITL 审批中心(危险操作/写文件/网络) |
| `/observability` | `Observability` | 事件流、Trace、Prometheus 指标 |
| `/tools` | `Tools` | MCP 工具注册表 / 启停 / 健康状态 |
| `/settings` | `Settings` | LLM Provider、模型、Embedding、容错参数 |
| `/prompts` | `Prompts` | Prompt 模板注册表(A/B 切换、热加载) |
| `/memory` | `Memory` | 记忆查看(Working/Episodic/Semantic/Procedural) |

### 3.2 状态管理
- `chatStore`(Zustand):会话列表、当前消息、流式订阅句柄、附件元数据。
- `uiStore`:主题、侧栏折叠、后端健康状态、Toast。
- 全局每 8s 调一次 `api.health()` 维护 `backendOnline` 指示灯。

### 3.3 数据流
```
User → Chat.tsx
        ↓
   chatStore.sendMessage()
        ↓
   api.streamChat()  ── SSE ──>  ai_agent.app.py
        ↓                              ↓
   assistant-ui Thread           LangGraph 节点机
        ↑                              ↓
   Stream Event(JSON)  ◀─── token/tool/observation/final
```

### 3.4 关键适配层
- `lib/api.ts`:统一 REST / SSE / WebSocket 客户端,封装重试、超时、错误提示。
- `lib/attachmentAdapter.ts`:把 `ai_agent` 上传响应转为 assistant-ui 可消费的附件。
- `lib/threadListAdapter.ts`:把后端会话列表映射为 assistant-ui ThreadListRuntime。
- `hooks/useAgentThreadListRuntime.ts`:封装会话刷新/创建/删除。

---

## 4. 配置说明

| 配置项 | 来源 | 作用 |
|---|---|---|
| `VITE_API_BASE` | 环境变量 | 自定义后端基址(默认 `/api` 代理) |
| `VITE_WS_BASE` | 环境变量 | WebSocket 基址 |
| `VITE_THEME` | 默认值 | `dark` / `light`,默认 `dark` |
| 后端 `.env` | `../ai_agent/.env` | LLM Provider、容错、记忆、MCP 配置 |

> Vite dev 默认代理:`/api → http://127.0.0.1:8000`,可在 `vite.config.ts` 调整。

---

## 5. 开发与自定义

### 5.1 新增页面
1. 在 `src/pages/` 创建 `MyPage.tsx`。
2. 在 `App.tsx` 路由表增加 `<Route path="/my" element={<MyPage />} />`。
3. 在 `Sidebar.tsx` 增加导航入口与图标。
4. 若需要全局状态,扩展 `chatStore` 或 `uiStore` 并附 `*.test.ts`。

### 5.2 新增后端能力接入
1. 在 `src/lib/api.ts` 暴露 `api.myEndpoint(...)`。
2. 若涉及 SSE / WS,封装在 `lib/api.ts` 内部以统一错误处理。
3. 在前端 hook 或 store 调用并把数据写入 store。
4. 加 Vitest 单元测试 + Playwright 端到端用例。

### 5.3 主题与样式
- 全局令牌在 `src/styles/globals.css`。
- 组件样式使用 Tailwind utility classes,搭配 `clsx` 条件类。
- 动画使用 `framer-motion`(已在 `Chat` 消息入场动画中示范)。

### 5.4 代码规范
- ESLint + Prettier(`npm run lint`)。
- `npm run check` 触发 `tsc --noEmit`。
- CI(`backend-ci.yml` / `ci.yml`)会强制 typecheck + vitest + actionlint。

---

## 6. 部署与运维

### 6.1 Docker(推荐)
```bash
# 仓库根目录
docker compose up -d --build    # 同时构建前端 + 后端镜像
# 访问 http://localhost:8000  (后端 + 静态前端一体化)
```
- 多阶段构建:Node 20-alpine 构建前端 → python:3.11-slim 运行 uvicorn。
- 内置 healthcheck `/api/health`,Compose 自动健康恢复。
- `docker:dev` profile 提供 Vite dev container。

### 6.2 GitHub Container Registry
```bash
docker pull ghcr.io/<owner>/ai-agent-console:latest
docker run -p 8000:8000 ghcr.io/<owner>/ai-agent-console:latest
```
发布流程由 `.github/workflows/docker-ci.yml` 自动触发。

### 6.3 静态站点(GitHub Pages)
- 工作流 `deploy.yml` 构建并发布 `dist/` 到 `gh-pages` 分支。
- 需先在仓库 Settings → Pages 选择 `gh-pages` 分支。

### 6.4 桌面二进制
- Windows / Linux 桌面包由 `../ai_agent/package_dist.ps1` 与 `build_linux.sh` 生成。
- 前端 `dist/` 已被嵌入到 PyInstaller 产物(`_internal/web/`)。

### 6.5 Scoop / Homebrew / PyPI
详见 `.github/PACKAGE_DISTRIBUTION.md` / `PYPI_PUBLISHING.md` / `SCOOP_BREW_TAP_SETUP.md`。

---

## 7. 评估与测试

| 类型 | 命令 | 范围 |
|---|---|---|
| 单元 | `npm test` | stores / lib / utils |
| 覆盖率 | `npm run test:coverage` | v8 coverage |
| 端到端 | `npm run e2e` | 关键页面 + 视觉基线 |
| 类型 | `npm run check` | 全量 TS |
| 工作流 | `npm run lint:workflows` | actionlint |
| 升级检查 | `npm run check-upgrades` | weekly-upgrades 工作流 |

---

## 8. 常见问题与故障排除

| 现象 | 排查 |
|---|---|
| 顶部状态灯红色 | 后端未启动 / 8000 端口被占 → `npm run docker:logs` 或重启 uvicorn |
| 聊天无响应 | LLM_API_KEY 未配置 → `../ai_agent/.env` 填写后重启后端 |
| Vite 代理 502 | 后端崩溃,查看终端 / Docker logs;`.env` 中 `HOST=0.0.0.0` |
| Tailwind class 不生效 | 检查 `tailwind.config.js` `content` 是否覆盖新文件 |
| Playwright 启动失败 | 先 `npm run e2e:install` 下载 chromium |
| Docker 构建慢 | 利用 `package*.json` cache,后续只复制 `src/` |
| TS 报错"Cannot find module '@/...'" | `tsconfig.json` `paths` 配置别名 `@/* -> src/*` |

---

## 9. 相关文档

- 顶层 [README.md](../README.md) · [QUICKSTART.md](../QUICKSTART.md) · [CHANGELOG.md](../CHANGELOG.md)
- 后端 [../ai_agent/README.md](../ai_agent/README.md) · [FEATURES_GUIDE.md](../ai_agent/FEATURES_GUIDE.md)
- 发布运维 [RELEASE.md](.github/RELEASE.md) · [RELEASE_PIPELINE.md](.github/RELEASE_PIPELINE.md)
- 包分发 [PACKAGE_DISTRIBUTION.md](.github/PACKAGE_DISTRIBUTION.md)
- GHCR [GHCR_SETUP.md](.github/GHCR_SETUP.md)
- PyPI [PYPI_PUBLISHING.md](.github/PYPI_PUBLISHING.md)
- Scoop/Brew [SCOOP_BREW_TAP_SETUP.md](.github/SCOOP_BREW_TAP_SETUP.md)