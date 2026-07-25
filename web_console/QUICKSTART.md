# Web Console 快速开始

> 5 分钟把 AI Agent 控制台跑起来。

## 0. 前置条件
- Node ≥ 20
- npm ≥ 10(或 pnpm/yarn)
- 后端 `../ai_agent` 可启动,已配置至少一个 `LLM_API_KEY`

## 1. 安装依赖
```bash
cd web_console
npm ci
```

## 2. 启动后端(单独终端)
```bash
cd ../ai_agent
pip install -r requirements.txt
cp .env.example .env       # 填入 LLM_API_KEY
python -m uvicorn ai_agent.web_ui:app --reload --port 8000
```

## 3. 启动前端
```bash
npm run dev
# 打开 http://localhost:5173
```

## 4. 验证
- 顶部状态灯为绿色 = 后端可达
- 进入 `Chat`,发送 "你好"
- 切到 `Tools` 查看 MCP 工具列表
- 切到 `Memory` 查看记忆条目

## 5. 跑测试
```bash
npm test               # 单元
npm run e2e:install    # 首次
npm run e2e            # 端到端
```

## 6. 打包 Docker
```bash
cd ..
docker compose up -d --build
# 访问 http://localhost:8000
```

## 7. 常用脚本
| 命令 | 说明 |
|---|---|
| `npm run dev` | 开发模式(HMR) |
| `npm run build` | 生产构建 |
| `npm run preview` | 预览生产构建 |
| `npm run check` | TypeScript 类型检查 |
| `npm test` | 单元测试 |
| `npm run test:coverage` | 覆盖率 |
| `npm run e2e` | 端到端 |
| `npm run lint:workflows` | actionlint 检查 GitHub Actions |
| `npm run check-upgrades` | 依赖升级检查 |