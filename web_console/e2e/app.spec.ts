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

  test('主题切换按钮工作（深色 ↔ 浅色）', async ({ page }) => {
    await page.goto('/');
    const themeBtn = page.getByRole('button', { name: /切换到(浅色|深色)主题/ }).first();
    await expect(themeBtn).toBeVisible();
    const before = await themeBtn.textContent();
    await themeBtn.click();
    await page.waitForTimeout(150);
    const after = await themeBtn.textContent();
    expect(before).not.toBe(after);
  });

  test('侧栏导航 8 个入口', async ({ page }) => {
    await page.goto('/');
    for (const label of ['Chat', 'Agents', 'Approval', 'Observability', 'Tools', 'Settings', 'Prompts', 'Memory']) {
      await expect(page.getByRole('link', { name: label, exact: true }).first()).toBeVisible();
    }
  });

  test('点击 Agents 路由切换', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Agents', exact: true }).first().click();
    // v2 slim：/agents 兼容重定向到 /admin?tab=agents
    await expect(page).toHaveURL(/\/admin\?tab=agents$/);
    // AdminPage 的 tablist 存在，Agents tab 被选中
    await expect(page.getByRole('tab', { name: 'Agents' })).toHaveAttribute('aria-selected', 'true');
  });

  test('点击 Tools 路由切换', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('link', { name: 'Tools', exact: true }).first().click();
    // v2 slim：/tools → /admin?tab=tools
    await expect(page).toHaveURL(/\/admin\?tab=tools$/);
    // Tools tab 被选中
    await expect(page.getByRole('tab', { name: 'Tools' })).toHaveAttribute('aria-selected', 'true');
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
