/**
 * P2-1 — resumeAgentStream 协议端到端（Vitest）
 *
 * 覆盖 P1-5 resume SSE 流客户端：
 *  - 标准 SSE 剧本（start → hitl_resumed → chunk → complete → end）
 *  - HTTP 404 → yield error 帧（带 phase: resume_http_status）
 *  - HTTP 500 → yield error 帧
 *  - fetch 抛错 → yield error 帧（带 phase: resume_fetch_throw）
 *  - 用户 abort → 静默退出
 *  - URL 包含 session_id query 参数
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

beforeEach(() => {
  vi.resetModules();
  vi.restoreAllMocks();
});

/** 把事件收集到数组。 */
async function collect<T>(gen: AsyncGenerator<T>): Promise<T[]> {
  const out: T[] = [];
  for await (const ev of gen) out.push(ev);
  return out;
}

function sse(events: Array<{ event: string; dataObj: unknown }>): string {
  const lines: string[] = [];
  for (const e of events) {
    lines.push(`event: ${e.event}`);
    lines.push(`data: ${JSON.stringify(e.dataObj)}`);
    lines.push('');
    lines.push('');
  }
  return lines.join('\n');
}

function makeSseStream(body: string): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(body));
        controller.close();
      },
    }),
    { status: 200, headers: { 'Content-Type': 'text/event-stream' } },
  );
}

describe('resumeAgentStream — 标准剧本', () => {
  it('解析 hitl_resumed + chunk + complete + end 序列', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    vi.spyOn(global, 'fetch').mockResolvedValue(
      makeSseStream(
        sse([
          { event: 'start', dataObj: { type: 'start', phase: 'hitl_resume', decision: 'rejected' } },
          { event: 'hitl_resumed', dataObj: { type: 'hitl_resumed', phase: 'rejected', tool_name: 'run_code' } },
          { event: 'chunk', dataObj: { type: 'chunk', data: '已为您跳过危险代码。' } },
          { event: 'complete', dataObj: { type: 'complete', data: '已为您跳过危险代码。' } },
          { event: 'end', dataObj: { type: 'end' } },
        ]),
      ),
    );

    const events = await collect(
      resumeAgentStream('rid-1', 'sid-A', new AbortController().signal),
    );

    const types = events.map((e) => (e as { event?: string }).event);
    expect(types).toContain('start');
    expect(types).toContain('hitl_resumed');
    expect(types).toContain('chunk');
    expect(types).toContain('complete');
    expect(types).toContain('end');

    const chunk = events.find((e) => (e as { event?: string }).event === 'chunk');
    expect((chunk as { dataObj?: { data?: string } })?.dataObj?.data).toBe(
      '已为您跳过危险代码。',
    );
  });

  it('HTTP 404 → yield error 帧（带 status 字段）', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('request not found', { status: 404 }),
    );

    const events = await collect(
      resumeAgentStream('rid-unknown', 'sid-A', new AbortController().signal),
    );
    const types = events.map((e) => (e as { event?: string }).event);
    expect(types).toContain('error');
    expect(types).toContain('end');

    const err = events.find((e) => (e as { event?: string }).event === 'error') as
      | { dataObj?: { phase?: string; status?: number } }
      | undefined;
    expect(err?.dataObj?.phase).toBe('resume_http_status');
    expect(err?.dataObj?.status).toBe(404);
  });

  it('HTTP 500 → yield error 帧', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('internal server error', { status: 500 }),
    );

    const events = await collect(
      resumeAgentStream('rid-X', 'sid-A', new AbortController().signal),
    );
    const err = events.find((e) => (e as { event?: string }).event === 'error') as
      | { dataObj?: { phase?: string; status?: number } }
      | undefined;
    expect(err?.dataObj?.status).toBe(500);
  });

  it('fetch 抛错 → yield error 帧（带 phase: resume_fetch_throw）', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('NetworkError'));

    const events = await collect(
      resumeAgentStream('rid-X', 'sid-A', new AbortController().signal),
    );
    const err = events.find((e) => (e as { event?: string }).event === 'error') as
      | { dataObj?: { phase?: string; error?: string } }
      | undefined;
    expect(err?.dataObj?.phase).toBe('resume_fetch_throw');
    expect(err?.dataObj?.error).toContain('NetworkError');
  });

  it('用户 abort → 不抛到外层（错误或空均可）', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    vi.spyOn(global, 'fetch').mockImplementation(async (_url, init) => {
      return new Promise((_, reject) => {
        if (init?.signal?.aborted) {
          reject(new DOMException('aborted', 'AbortError'));
          return;
        }
        init?.signal?.addEventListener(
          'abort',
          () => reject(new DOMException('aborted', 'AbortError')),
          { once: true },
        );
      });
    });

    const ac = new AbortController();
    const promise = collect(resumeAgentStream('rid-X', 'sid-A', ac.signal));
    await Promise.resolve();
    ac.abort();

    // 不应抛到外层（collect 完成即可）
    const events = await promise;
    // 至少有一个事件；可以空（abort 时静默）或 error + end（兜底）
    expect(events).toBeDefined();
  });

  it('URL 拼接 session_id 作为 query 参数', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    let capturedUrl = '';
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      capturedUrl = String(url);
      return makeSseStream(sse([{ event: 'end', dataObj: { type: 'end' } }]));
    });

    await collect(resumeAgentStream('rid-1', 'sid-ABC', new AbortController().signal));
    expect(capturedUrl).toContain('/api/chat/rid-1/resume');
    expect(capturedUrl).toContain('session_id=sid-ABC');
  });

  it('baseUrl 可覆盖根域', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    let capturedUrl = '';
    vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      capturedUrl = String(url);
      return makeSseStream(sse([{ event: 'end', dataObj: { type: 'end' } }]));
    });

    await collect(
      resumeAgentStream('rid-1', 'sid-A', new AbortController().signal, {
        baseUrl: 'https://api.example.com',
      }),
    );
    expect(capturedUrl.startsWith('https://api.example.com/')).toBe(true);
  });

  it('approved 决策：resume 流含 tool_result 帧（前端据此累积 ✅ 提示）', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    vi.spyOn(global, 'fetch').mockResolvedValue(
      makeSseStream(
        sse([
          { event: 'start', dataObj: { type: 'start', decision: 'approved' } },
          { event: 'hitl_resumed', dataObj: { type: 'hitl_resumed', phase: 'approved' } },
          {
            event: 'tool_result',
            dataObj: {
              type: 'tool_result',
              tool_call_id: 'tc-1',
              name: 'run_code',
              result: '4',
              duration_ms: 12,
            },
          },
          {
            event: 'tool_end',
            dataObj: {
              type: 'tool_end',
              tool_call_id: 'tc-1',
              name: 'run_code',
              status: 'success',
              duration_ms: 12,
            },
          },
          { event: 'chunk', dataObj: { type: 'chunk', data: '已执行，结果是 4' } },
          { event: 'complete', dataObj: { type: 'complete', data: '已执行，结果是 4' } },
          { event: 'end', dataObj: { type: 'end' } },
        ]),
      ),
    );

    const events = await collect(
      resumeAgentStream('rid-1', 'sid-A', new AbortController().signal),
    );
    const types = events.map((e) => (e as { event?: string }).event);
    expect(types).toContain('tool_result');
    expect(types).toContain('tool_end');
    expect(types).toContain('chunk');
  });

  it('流没有 end 帧时仍 yield end 帧（兜底）', async () => {
    const { resumeAgentStream } = await import('./agentStreamResume');
    vi.spyOn(global, 'fetch').mockResolvedValue(
      makeSseStream(
        sse([
          { event: 'chunk', dataObj: { type: 'chunk', data: 'ok' } },
          // 没有 end 帧
        ]),
      ),
    );

    const events = await collect(
      resumeAgentStream('rid-1', 'sid-A', new AbortController().signal),
    );
    const types = events.map((e) => (e as { event?: string }).event);
    expect(types).toContain('chunk');
    // 应有兜底 end 帧
    expect(types).toContain('end');
  });
});
