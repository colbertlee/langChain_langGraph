import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E 配置
 *
 * 包含两层测试：
 * 1. 功能测试（app.spec.ts）—— 路由 / 主题 / 输入
 * 2. 视觉回归（visual.spec.ts）—— toHaveScreenshot baseline diff
 *
 * 启动方式：Playwright 自动启动 dev server（webServer 字段），
 * 不用手动 npm run dev。
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,
  // 视觉回归阈值：50% 像素差匹配（动画 / 时间敏感）
  expect: {
    toHaveScreenshot: {
      maxDiffPixels: 50,
      threshold: 0.2,
      animations: 'disabled',
    },
  },
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: 'npm run dev -- --host 127.0.0.1 --port 5173',
        url: 'http://127.0.0.1:5173',
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
        stdout: 'pipe',
        stderr: 'pipe',
      },
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
