/**
 * mockSse — E2E 测试用 SSE 注入工具
 *
 * 设计：
 *  - 在 Playwright spec 里调用 installMockSseRoutes(page)，拦截 /api/chat/stream
 *    与 /api/chat/{rid}/resume，把传入的「剧本」events 序列化为符合后端协议的 SSE 字节流。
 *  - 同时拦截 /api/tools 让前端 tools 列表稳定（避免 500）。
 *  - 「剧本」用高阶对象描述（P0-1 工具事件 / P1-2 retry / thinking / approval_required），
 *    mockSse 负责序列化。
 *
 * 用法（Playwright spec）：
 *   await page.goto('/chat');
 *   await installMockSseRoutes(page, [
 *     { type: 'start' },
 *     { type: 'thinking', data: '需要调用 run_code' },
 *     { type: 'tool_start', tool_call_id: 't-1', name: 'run_code', args: { code: '1+1' } },
 *     { type: 'tool_call', name: 'run_code', tool_call_id: 't-1' },
 *     { type: 'chunk', data: '## 回答\n答案是 2' },
 *     { type: 'tool_result', tool_call_id: 't-1', name: 'run_code', result: '2', duration_ms: 50 },
 *     { type: 'tool_end', tool_call_id: 't-1', name: 'run_code', status: 'success', duration_ms: 50 },
 *     { type: 'complete', data: '## 回答\n答案是 2' },
 *     { type: 'end' },
 *   ]);
 *
 * 注意：
 *  - 每个剧本调用一次 /api/chat/stream，按 FIFO 顺序消耗；
 *  - 想要 retry 场景：在第一次返回带 retryable=true 的 error，第二次返回成功剧本。
 */

import type { Page, Route, Request } from '@playwright/test';

export type ScriptEvent =
  // 通用事件
  | { type: 'start'; meta?: Record<string, unknown> }
  | { type: 'safety'; data: string }
  | { type: 'thinking'; data: string }
  | { type: 'chunk'; data: string }
  | { type: 'complete'; data: string }
  | { type: 'end' }
  | { type: 'agent_switch'; agent: string; reason?: string }
  | { type: 'agent_done'; agent?: string }
  // 工具事件族（P0-1）
  | {
      type: 'tool_start';
      tool_call_id: string;
      name: string;
      args: Record<string, unknown>;
    }
  | { type: 'tool_call'; name: string; tool_call_id: string }
  | {
      type: 'tool_result';
      tool_call_id: string;
      name: string;
      result: string;
      duration_ms?: number;
    }
  | {
      type: 'tool_end';
      tool_call_id: string;
      name: string;
      status: 'success' | 'error' | 'aborted';
      duration_ms?: number;
    }
  // HITL（P1-5 复用）
  | {
      type: 'approval_required';
      request_id: string;
      tool_name: string;
      tool_args: Record<string, unknown>;
      reason?: string;
      timeout_seconds?: number;
    }
  // 错误事件（P1-2 retryable）
  | {
      type: 'error';
      data: string;
      retryable?: boolean;
      phase?: string;
    };

/**
 * 把单个 ScriptEvent 序列化为 SSE 字节块（包含 \n\n 终止符）。
 */
export function serializeSseEvent(ev: ScriptEvent): string {
  const obj: Record<string, unknown> = { type: ev.type };
  if ('data' in ev) obj.data = ev.data;
  if ('name' in ev) obj.name = (ev as { name?: string }).name;
  if ('args' in ev) obj.args = (ev as { args?: unknown }).args;
  if ('tool_call_id' in ev)
    obj.tool_call_id = (ev as { tool_call_id?: string }).tool_call_id;
  if ('result' in ev) obj.result = (ev as { result?: string }).result;
  if ('duration_ms' in ev)
    obj.duration_ms = (ev as { duration_ms?: number }).duration_ms;
  if ('status' in ev) obj.status = (ev as { status?: string }).status;
  if ('retryable' in ev)
    obj.retryable = (ev as { retryable?: boolean }).retryable;
  if ('phase' in ev) obj.phase = (ev as { phase?: string }).phase;
  if ('tool_name' in ev)
    obj.tool_name = (ev as { tool_name?: string }).tool_name;
  if ('tool_args' in ev)
    obj.tool_args = (ev as { tool_args?: unknown }).tool_args;
  if ('reason' in ev)
    obj.reason = (ev as { reason?: string }).reason;
  if ('timeout_seconds' in ev)
    obj.timeout_seconds = (ev as { timeout_seconds?: number }).timeout_seconds;
  if ('meta' in ev) Object.assign(obj, (ev as { meta?: Record<string, unknown> }).meta);
  if ('agent' in ev) obj.agent = (ev as { agent?: string }).agent;

  const data = JSON.stringify(obj);
  return `event: ${ev.type}\ndata: ${data}\n\n`;
}

/**
 * 把完整剧本序列化为 SSE 字节流（utf-8）。
 */
export function scriptToSseBytes(scripts: ScriptEvent[]): Buffer {
  const out = scripts.map(serializeSseEvent).join('');
  return Buffer.from(out, 'utf-8');
}

/**
 * 安装 mock 路由：
 *   - /api/chat/stream   按 FIFO 消耗 streamScripts
 *   - /api/chat/{rid}/resume 按 FIFO 消耗 resumeScripts（缺省自动给空剧本）
 *   - /api/chat/approve / /api/chat/reject  返回固定 JSON（带 resume_url）
 *   - /api/tools         返回空 tools 列表（避免 500）
 *   - /api/tools/v1/*    透传 / 默认
 */
export async function installMockSseRoutes(
  page: Page,
  options: {
    streamScripts?: ScriptEvent[][]; // 每个 POST 消耗一条剧本
    resumeScripts?: Record<string, ScriptEvent[]>;
    onApprove?: (rid: string) => ScriptEvent[];
    onReject?: (rid: string) => ScriptEvent[];
  } = {},
): Promise<void> {
  let streamIdx = 0;
  const streamScripts = options.streamScripts ?? [];

  await page.route('**/api/chat/stream', async (route: Route, req: Request) => {
    const script =
      streamScripts[Math.min(streamIdx, streamScripts.length - 1)] ??
      streamScripts[0] ??
      [];
    streamIdx += 1;
    const body = scriptToSseBytes(script);
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: {
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
      body,
    });
  });

  await page.route('**/api/chat/*/resume', async (route: Route) => {
    const url = route.request().url();
    const m = url.match(/\/api\/chat\/([^/]+)\/resume/);
    const rid = m?.[1] ?? 'unknown';
    const script = options.resumeScripts?.[rid] ?? [
      { type: 'start' as const },
      { type: 'chunk' as const, data: '续生成内容' },
      { type: 'complete' as const, data: '续生成内容' },
      { type: 'end' as const },
    ];
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      headers: { 'Cache-Control': 'no-cache' },
      body: scriptToSseBytes(script),
    });
  });

  await page.route('**/api/chat/approve', async (route) => {
    let rid = 'rid-unknown';
    try {
      const data = route.request().postDataJSON();
      if (data?.request_id) rid = String(data.request_id);
    } catch {
      /* ignore */
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        success: true,
        decision: 'approved',
        request_id: rid,
        tool_name: 'mock_tool',
        session_id: 'mock',
        resume_url: `/api/chat/${rid}/resume`,
      }),
    });
  });

  await page.route('**/api/chat/reject', async (route) => {
    let rid = 'rid-unknown';
    try {
      const data = route.request().postDataJSON();
      if (data?.request_id) rid = String(data.request_id);
    } catch {
      /* ignore */
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        success: true,
        decision: 'rejected',
        request_id: rid,
        reason: '用户主动拒绝',
        tool_name: 'mock_tool',
        session_id: 'mock',
        resume_url: `/api/chat/${rid}/resume`,
      }),
    });
  });

  await page.route('**/api/tools', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        tools: [
          {
            name: 'run_code',
            description: '执行 Python 代码（mock）',
            extras: { source: 'v2_slim' },
          },
          {
            name: 'file_ops',
            description: '文件操作复合工具（mock）',
            extras: { source: 'v2_slim' },
          },
          {
            name: 'knowledge_search',
            description: '本地知识库检索（mock）',
            extras: { source: 'v21_tools.rag_tool' },
          },
        ],
      }),
    });
  });

  // 其余未知 API：返回 404，避免 Vite 抛错
  await page.route('**/api/**', async (route) => {
    if (route.request().method() === 'OPTIONS') {
      await route.fulfill({ status: 204, body: '' });
      return;
    }
    await route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'mock-not-found' }),
    });
  });
}

/**
 * 兜底：如果 spec 没安装 mock 路由但页面发请求，统一返回 200 空响应（避免 vite 报 500）。
 */
export async function installCatchAllMock(page: Page): Promise<void> {
  await page.route('**/api/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
}
