import { test, expect } from '@playwright/test';

/**
 * 视觉回归测试
 *
 * 用法：
 *   首次跑 → 自动生成 baseline（*.png 在 e2e/visual.spec.ts-snapshots/）
 *   后续跑 → 与 baseline 像素 diff，>50px 差异则失败
 *   主动更新：rm -rf e2e/visual.spec.ts-snapshots && npm run e2e
 *   仅截图：npx playwright test visual.spec.ts --update-snapshots
 *
 * 截图覆盖：首页加载、Agents 页、Tools 页、深色主题、侧栏折叠
 */

test.describe('视觉回归', () => {
  test.beforeEach(async ({ page }) => {
    // 关闭动画避免时间敏感的像素抖动
    await page.addStyleTag({
      content: '*, *::before, *::after { animation: none !important; transition: none !important; }',
    });
  });

  test('Chat 首页快照', async ({ page }) => {
    await page.goto('/');
    // 等首屏稳定
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('chat-home.png', { fullPage: false });
  });

  test('Chat 首页（侧栏展开）', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.locator('body')).toHaveScreenshot('chat-full.png');
  });

  test('Agents 页快照', async ({ page }) => {
    await page.goto('/agents');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('agents.png');
  });

  test('Tools 页快照', async ({ page }) => {
    await page.goto('/tools');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('tools.png');
  });

  test('Approval 页快照', async ({ page }) => {
    await page.goto('/approval');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('approval.png');
  });

  test('Settings 页快照', async ({ page }) => {
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');
    await expect(page).toHaveScreenshot('settings.png');
  });

  test('深色主题颜色调色板', async ({ page }) => {
    await page.goto('/');
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    expect(bg).toBe('rgb(10, 10, 11)'); // #0A0A0B
    await expect(page.locator('body')).toHaveScreenshot('theme-palette.png');
  });
});
