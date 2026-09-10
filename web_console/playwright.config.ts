/**
 * Playwright E2E 配置（P2-1）
 *
 * 设计要点：
 *  - 不依赖真实后端：所有 spec 通过 page.route() 拦截 /api/chat/stream 注入 mock SSE；
 *    这样测试快（< 10s/case）、可重复、无网络。
 *  - webServer 启动 Vite dev server（端口 5173）—— 与本地 npm run dev 一致；
 *    URL env E2E_BASE_URL 可覆盖（CI 用 preview 模式）。
 *  - 视觉回归走 visual.spec.ts（在另一份配置里）；这里只跑功能性 e2e。
 *  - 单进程跑（workers=1）—— 共享同一份持久化 localStorage 简化状态断言。
 *  - 不安装 WebKit/Firefox —— chromium only（CI 启动时间最少）。
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // 排除 visual.spec.ts（走独立配置避免冲突）
  testIgnore: ['**/visual.spec.ts'],
  fullyParallel: false,
  workers: 1,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
    screenshot: 'only-on-failure',
    // 关闭 networkidle 等待——SSE 流永远不空闲
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
        // 关闭 webkit/firefox 以减小 CI 体积
      },
    },
  ],
  webServer: process.env.E2E_NO_WEBSERVER
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 5173',
        url: 'http://127.0.0.1:5173',
        reuseExistingServer: true,
        timeout: 60_000,
        stdout: 'pipe',
        stderr: 'pipe',
      },
});
