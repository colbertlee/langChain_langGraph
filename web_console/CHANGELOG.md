# Web Console Changelog

所有 notable 变更都记录在此文件。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [2.0.0] - 2026-07-25

### Added
- 路由扩展:`/agents` `/approval` `/observability` `/tools` `/settings` `/prompts` `/memory`
- Zustand 双 store:`chatStore` 会话流 / `uiStore` 主题与健康灯
- assistant-ui 适配层:`threadListAdapter`、`attachmentAdapter`、`useAgentThreadListRuntime`
- 多阶段 Dockerfile(前端 Node 20-alpine 构建 → 后端 python:3.11-slim 运行)
- Playwright 视觉基线 + E2E 工作流
- actionlint 工作流体检
- weekly-upgrades 依赖升级机器人

### Changed
- React 19.2 + react-router 6.26 + Vite 5.4
- Tailwind 3.4 + framer-motion 11
- 全局每 8s 调用 `/api/health` 维护 UI 状态灯
- 端到端覆盖:Chat 输入、侧栏导航、Agents/Tools 路由、深色主题

### Fixed
- 会话列表在长上下文下滑动卡顿 → Zustand 选择器细粒度订阅
- 附件上传失败后未清理本地预览 → onError 统一释放
- Tailwind 深色主题背景缺失 → `globals.css` 增补深空黑令牌
- Sidebar 折叠按钮无障碍焦点 → `aria-expanded` + 键盘测试
- Vite dev 代理偶发 502 → 长连接空闲超时调高

### Security
- 危险操作(写文件、Shell、网络)统一走 `Approval` 中心
- LLM API Key 仅在后端保存,前端不持有
- 静态前端无服务端渲染,降低 XSS 表面

---

## [1.2.0] - 2026-03

### Added
- Chat 流式输出 + 工具调用可视化
- 侧栏会话列表与新建会话
- 深色主题

### Fixed
- 路由切换闪烁 → `Suspense` 占位
- Markdown 渲染 XSS → DOMPurify 净化

---

## [1.0.0] - 2025-11

- 首版:Chat 页面 + REST 客户端 + Vite + Tailwind