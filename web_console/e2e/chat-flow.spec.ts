/**
 * P2-1 — 真实对话 E2E（Playwright）
 *
 * 覆盖：
 *  - P0-1：tool_start / tool_call / chunk / tool_result / tool_end 事件族 → UI 渲染
 *    - ToolCard 显示 args + result（菊花消失）
 *    - 工具完成后 yield 简短 ✅ 提示
 *  - P0-2：thinking 事件 → ThinkingBlock 折叠块
 *  - P1-2：retryable=true → 自动重试 → UI 显示「网络不稳定，正在重试」
 *  - P1-5：approval_required → 用户 reject → 后端响应 resume_url → 前端订阅 resume SSE
 *    → ResumeDrawer 显示续生成内容
 *
 * 不依赖真实后端：所有 /api/** 通过 page.route mock。
 */

import { test, expect, type Page } from '@playwright/test';
import { installMockSseRoutes } from './mockSse';

async function gotoChat(page: Page) {
  await page.goto('/');
  // 等 assistant-ui runtime 初始化完成（textarea 出现）
  const ta = page.locator('textarea[placeholder*="回车"]').first();
  await expect(ta).toBeVisible({ timeout: 15_000 });
  return ta;
}

test.describe('Chat 流对话（P0 / P1 协议端到端）', () => {
  test('发送消息 → 工具卡片显示 args + result（菊花消失）', async ({ page }) => {
    await installMockSseRoutes(page, {
      streamScripts: [
        [
          { type: 'start' },
          { type: 'thinking', data: '## 思考\n需要调用 run_code' },
          {
            type: 'tool_start',
            tool_call_id: 't-1',
            name: 'run_code',
            args: { code: '1+1' },
          },
          { type: 'tool_call', name: 'run_code', tool_call_id: 't-1' },
          { type: 'chunk', data: '## 回答\n' },
          {
            type: 'tool_result',
            tool_call_id: 't-1',
            name: 'run_code',
            result: '2',
            duration_ms: 87,
          },
          {
            type: 'tool_end',
            tool_call_id: 't-1',
            name: 'run_code',
            status: 'success',
            duration_ms: 87,
          },
          { type: 'chunk', data: '答案是 2' },
          { type: 'complete', data: '## 回答\n答案是 2' },
          { type: 'end' },
        ],
      ],
    });

    const ta = await gotoChat(page);
    await ta.fill('用 Python 算 1+1');
    await ta.press('Enter');

    // 等工具卡片出现（按 toolName 精确匹配）
    const toolCard = page.locator('[data-testid="tool-fallback"][data-tool-name="run_code"]').first();
    await expect(toolCard).toBeVisible({ timeout: 10_000 });

    // 卡片显示 running=true（tool_start 后），再切换到 running=false（tool_result 后）
    await expect(toolCard).toHaveAttribute('data-running', 'true', { timeout: 5_000 });
    await expect(toolCard).toHaveAttribute('data-running', 'false', { timeout: 10_000 });

    // 展开卡片（点击 header）→ 看到 Arguments + Result
    await page.locator('[data-testid="tool-fallback-header"]').first().click();
    await expect(page.getByText('Arguments').first()).toBeVisible();
    await expect(page.getByText('"code": "1+1"').first()).toBeVisible();
    await expect(page.getByText('Result').first()).toBeVisible();
    await expect(page.getByText(/^\s*2\s*$/).first()).toBeVisible();

    // ✅ 工具完成提示
    await expect(page.getByText(/✅.*run_code.*完成/).first()).toBeVisible({
      timeout: 5_000,
    });

    // 回答正文
    await expect(page.getByText(/答案是 2/).first()).toBeVisible();
  });

  test('thinking 事件折叠渲染为 ThinkingBlock', async ({ page }) => {
    await installMockSseRoutes(page, {
      streamScripts: [
        [
          { type: 'start' },
          { type: 'thinking', data: '先分析问题；然后给出结论。' },
          { type: 'thinking', data: '这是第二段思考。' },
          { type: 'chunk', data: '## 回答\n结论如下' },
          { type: 'complete', data: '## 回答\n结论如下' },
          { type: 'end' },
        ],
      ],
    });

    const ta = await gotoChat(page);
    await ta.fill('分析问题');
    await ta.press('Enter');

    // 等回答正文出现
    await expect(page.getByText(/结论如下/).first()).toBeVisible({ timeout: 10_000 });

    // ThinkingBlock summary 出现
    await expect(page.getByText(/思考过程/).first()).toBeVisible({ timeout: 5_000 });

    // 点击 summary 展开 → 内容可见
    await page.getByText(/思考过程/).first().click();
    await expect(page.getByText(/先分析问题/).first()).toBeVisible({ timeout: 3_000 });
    await expect(page.getByText(/第二段思考/).first()).toBeVisible();
  });

  test('retryable 错误 → 自动重试 + UI 横幅', async ({ page }) => {
    // 第一次请求：返回 retryable error；第二次：成功剧本
    await installMockSseRoutes(page, {
      streamScripts: [
        // 第一次：retryable error → 流静默断开（不带 complete）
        [
          { type: 'start' },
          {
            type: 'error',
            data: 'Stream ended without terminal event',
            retryable: true,
            phase: 'stream_silent_close',
          },
          { type: 'end' },
        ],
        // 第二次（重试）：成功
        [
          { type: 'start' },
          { type: 'chunk', data: '重试成功！' },
          { type: 'complete', data: '重试成功！' },
          { type: 'end' },
        ],
      ],
    });

    const ta = await gotoChat(page);
    await ta.fill('触发重试');
    await ta.press('Enter');

    // UI 显示「网络不稳定，正在自动重试」
    await expect(page.getByText(/网络不稳定.*自动重试/).first()).toBeVisible({
      timeout: 8_000,
    });

    // 重试成功后正文出现
    await expect(page.getByText(/重试成功/).first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test('不可重试错误（retryable=false）→ 不再重试，直接显示错误', async ({ page }) => {
    await installMockSseRoutes(page, {
      streamScripts: [
        [
          { type: 'start' },
          {
            type: 'error',
            data: 'Validation failed: empty message',
            retryable: false,
            phase: 'event_gen',
          },
          { type: 'end' },
        ],
      ],
    });

    const ta = await gotoChat(page);
    await ta.fill('触发不可重试错误');
    await ta.press('Enter');

    // UI 应显示错误提示，但不应出现「自动重试」横幅
    await expect(page.getByText(/Validation failed/).first()).toBeVisible({
      timeout: 10_000,
    });
    // 不会有重试提示
    await expect(page.getByText(/网络不稳定.*自动重试/)).not.toBeVisible({ timeout: 2_000 });
  });

  test('approval_required → reject → ResumeDrawer 显示续生成内容', async ({ page }) => {
    await installMockSseRoutes(page, {
      streamScripts: [
        [
          { type: 'start' },
          {
            type: 'approval_required',
            request_id: 'rid-flow-1',
            tool_name: 'run_code',
            tool_args: { code: "print('dangerous')" },
            reason: '执行危险代码需要审批',
            timeout_seconds: 300,
          },
          { type: 'chunk', data: '等待审批中…' },
          { type: 'end' },
        ],
      ],
      resumeScripts: {
        'rid-flow-1': [
          { type: 'start' },
          { type: 'hitl_resumed', data: '', phase: 'rejected' },
          { type: 'chunk', data: '好的，已为您跳过危险代码。' },
          { type: 'chunk', data: '我建议改用安全的查询方式。' },
          { type: 'complete', data: '好的，已为您跳过危险代码。我建议改用安全的查询方式。' },
          { type: 'end' },
        ],
      },
    });

    const ta = await gotoChat(page);
    await ta.fill('执行危险代码');
    await ta.press('Enter');

    // 审批卡片出现
    const rejectBtn = page.locator('[data-testid="approval-card-reject"]').first();
    await expect(rejectBtn).toBeVisible({ timeout: 10_000 });

    // resume 状态指示灯（resuming 时显示）
    const resuming = page.locator('[data-testid="approval-card-resuming"]').first();

    await rejectBtn.click();

    // ResumeDrawer 出现并累积续生成文本
    const drawer = page.locator('[data-testid="resume-drawer"]').first();
    await expect(drawer).toBeVisible({ timeout: 10_000 });

    // resuming 指示灯可能在某个瞬间出现（best-effort）
    try {
      await expect(resuming).toBeVisible({ timeout: 1000 });
    } catch {
      /* 可能太快跳过；不强制 */
    }

    // 续生成内容
    await expect(page.getByText(/已为您跳过危险代码/).first()).toBeVisible({
      timeout: 5_000,
    });
    await expect(page.getByText(/安全的查询方式/).first()).toBeVisible();

    // 关闭 drawer
    await page.locator('[data-testid="resume-drawer-close"]').first().click();
    await expect(drawer).not.toBeVisible({ timeout: 2_000 });
  });

  test('approval_required → approve → ResumeDrawer 显示续生成', async ({ page }) => {
    await installMockSseRoutes(page, {
      streamScripts: [
        [
          { type: 'start' },
          {
            type: 'approval_required',
            request_id: 'rid-approve-1',
            tool_name: 'run_code',
            tool_args: { code: '2+2' },
            reason: '需要审批',
            timeout_seconds: 300,
          },
          { type: 'end' },
        ],
      ],
      resumeScripts: {
        'rid-approve-1': [
          { type: 'start' },
          { type: 'hitl_resumed', data: '', phase: 'approved' },
          {
            type: 'tool_result',
            tool_call_id: 't-approve',
            name: 'run_code',
            result: '4',
            duration_ms: 12,
          },
          {
            type: 'tool_end',
            tool_call_id: 't-approve',
            name: 'run_code',
            status: 'success',
            duration_ms: 12,
          },
          { type: 'chunk', data: '已执行，结果是 4' },
          { type: 'complete', data: '已执行，结果是 4' },
          { type: 'end' },
        ],
      },
    });

    const ta = await gotoChat(page);
    await ta.fill('执行 2+2');
    await ta.press('Enter');

    const approveBtn = page.locator('[data-testid="approval-card-approve"]').first();
    await expect(approveBtn).toBeVisible({ timeout: 10_000 });
    await approveBtn.click();

    const drawer = page.locator('[data-testid="resume-drawer"]').first();
    await expect(drawer).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/已执行，结果是 4/).first()).toBeVisible({
      timeout: 5_000,
    });
  });
});

test.describe('Chat 流对话 — 边缘场景', () => {
  test('空剧本 → 仅 user 消息出现，无 assistant 回复', async ({ page }) => {
    await installMockSseRoutes(page, {
      streamScripts: [[{ type: 'start' }, { type: 'end' }]],
    });
    const ta = await gotoChat(page);
    await ta.fill('ping');
    await ta.press('Enter');
    // user 消息出现（input 文本被 echo）
    await expect(page.getByText('ping').first()).toBeVisible({ timeout: 5_000 });
    // assistant 不应有回答
    await expect(page.getByText(/重试成功/)).not.toBeVisible({ timeout: 2_000 });
  });

  test('Tools 页能列出 mock 工具', async ({ page }) => {
    await installMockSseRoutes(page, {
      streamScripts: [[{ type: 'start' }, { type: 'end' }]],
    });
    await page.goto('/');
    // 找到 Tools 链接
    await page.getByRole('link', { name: 'Tools', exact: true }).first().click();
    await expect(page).toHaveURL(/\/admin\?tab=tools/);
    // 等待 mock 列表加载
    await expect(page.getByText(/run_code/).first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/file_ops/).first()).toBeVisible();
    await expect(page.getByText(/knowledge_search/).first()).toBeVisible();
  });
});
