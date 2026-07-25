import { test, expect } from '@playwright/test';

/**
 * 纯前端 E2E 用例（不依赖后端）
 * - 加载页面
 * - 路由切换
 * - 新建会话
 * - 主题色（深色）
 * - 侧栏折叠
 */
test.describe('App 基础功能', () => {
  test('首页加载 + 显示 Agent Console 标题', async ({ page }) => {
    await page.goto('/');
    // 等 assistant-ui runtime 初始化
    await expect(page.locator('text=Agent Console').first()).toBeVisible({ timeout: 10000 });
    // 输入框存在
    await expect(page.locator('textarea[placeholder*="回车"]')).toBeVisible();
  });

  test('新建会话按钮可点击', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('新建会话').first()).toBeVisible();
    const initialUrl = page.url();
    await page.getByText('新建会话').first().click();
    // URL 应保持（前端路由）
    expect(page.url()).toBe(initialUrl);
  });

  test('侧栏导航 6 个入口', async ({ page }) => {
    await page.goto('/');
    for (const label of ['Chat', 'Agents', 'Approval', 'Observability', 'Tools', 'Settings']) {
      await expect(page.getByRole('link', { name: label, exact: true }).first()).toBeVisible();
    }
  });

  test('点击 Agents 路由切换', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Agents', exact: true }).first().click();
    await expect(page).toHaveURL(/\/agents$/);
    // 标题栏显示 Agents
    await expect(page.getByText('多 Agent 集群状态', { exact: false })).toBeVisible();
  });

  test('点击 Tools 路由切换', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Tools', exact: true }).first().click();
    await expect(page).toHaveURL(/\/tools$/);
    await expect(page.getByPlaceholder(/搜索工具/)).toBeVisible();
  });

  test('深色主题：背景深空黑', async ({ page }) => {
    await page.goto('/');
    const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
    // #0A0A0B = rgb(10, 10, 11)
    expect(bg).toMatch(/rgb\(10,\s*10,\s*11\)|rgba\(10,\s*10,\s*11/);
  });

  test('侧栏折叠按钮工作', async ({ page }) => {
    await page.goto('/');
    const aside = page.locator('aside').first();
    const before = await aside.boundingBox();
    await page.getByLabel('toggle sidebar').click();
    await page.waitForTimeout(400);
    const after = await aside.boundingBox();
    expect(after?.width).toBeLessThan(before?.width ?? 0);
  });
});

test.describe('Chat 输入框交互', () => {
  test('输入文字可见', async ({ page }) => {
    await page.goto('/');
    const ta = page.locator('textarea[placeholder*="回车"]');
    await ta.fill('hello world');
    await expect(ta).toHaveValue('hello world');
  });

  test('Enter 发送（无后端时显示错误提示）', async ({ page }) => {
    await page.goto('/');
    const ta = page.locator('textarea[placeholder*="回车"]');
    await ta.fill('ping');
    await ta.press('Enter');
    // 无后端或后端无 agent，应在几秒内渲染 user 消息
    await expect(page.getByText('ping', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });
});
