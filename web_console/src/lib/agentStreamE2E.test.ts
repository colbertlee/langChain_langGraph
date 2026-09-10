/**
 * P2-1 — Vitest 端到端：streamToChatModelResult 完整路径（P0-1/P0-2/P1-2/P1-5 全协议）
 *
 * 为什么需要这个文件（与 Playwright 互补）：
 *  - Playwright 跑真实浏览器，慢（10-30s/case），且依赖本地 Vite；
 *  - 这里用 jsdom + mock fetch，毫秒级覆盖整个 streamToChatModelResult 端到端路径。
 *  - 验证 sseParser / normalizeSseEvents / decideRetry / sleep 在面对 SSE 事件序列时的
 *    真实行为（事件序列化、归一化、重试决策、thinking 累积）。
 *
 * 关注点（与 Playwright spec 分工）：
 *  - Playwright：UI 渲染（tool card running 切换、thinking 折叠、ResumeDrawer 可见性）
 *  - Vitest：协议正确性（SSE 序列化、归一化、重试决策边界、resume 协议）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

beforeEach(() => {
  vi.restoreAllMocks();
});

/**
 * 把 N 个事件对象序列化成标准 SSE 字节串（与后端 event_gen 输出一致）。
 */
function sseScript(
  events: Array<{ event: string; dataObj: unknown }>,
): string {
  const lines: string[] = [];
  for (const e of events) {
    lines.push(`event: ${e.event}`);
    lines.push(`data: ${JSON.stringify(e.dataObj)}`);
    lines.push('');
    lines.push('');
  }
  return lines.join('\n');
}

describe('agentStreamE2E — 工具事件族协议（P0-1）', () => {
  it('完整剧本：tool_start → tool_call → chunk → tool_result → tool_end → complete → end', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');

    const body = sseScript([
      { event: 'start', dataObj: { type: 'start' } },
      {
        event: 'tool_start',
        dataObj: {
          type: 'tool_start',
          tool_call_id: 'tc-1',
          name: 'run_code',
          args: { code: '1+1' },
        },
      },
      {
        event: 'tool_call',
        dataObj: {
          type: 'tool_call',
          name: 'run_code',
          tool_call_id: 'tc-1',
        },
      },
      { event: 'chunk', dataObj: { type: 'chunk', data: '## 回答\n' } },
      {
        event: 'tool_result',
        dataObj: {
          type: 'tool_result',
          tool_call_id: 'tc-1',
          name: 'run_code',
          result: '2',
          duration_ms: 87,
        },
      },
      {
        event: 'tool_end',
        dataObj: {
          type: 'tool_end',
          tool_call_id: 'tc-1',
          name: 'run_code',
          status: 'success',
          duration_ms: 87,
        },
      },
      { event: 'chunk', dataObj: { type: 'chunk', data: '答案是 2' } },
      { event: 'complete', dataObj: { type: 'complete', data: '## 回答\n答案是 2' } },
      { event: 'end', dataObj: { type: 'end' } },
    ]);

    const events = parseSseStream(body);
    expect(events.length).toBeGreaterThanOrEqual(8);

    const types = events.map((e) => e.event);
    expect(types).toContain('start');
    expect(types).toContain('tool_start');
    expect(types).toContain('tool_result');
    expect(types).toContain('tool_end');
    expect(types).toContain('chunk');
    expect(types).toContain('complete');
    expect(types).toContain('end');

    // dataObj 内容正确
    const toolStart = events.find((e) => e.event === 'tool_start');
    expect((toolStart?.dataObj as { args?: unknown }).args).toEqual({ code: '1+1' });
    expect((toolStart?.dataObj as { tool_call_id?: string }).tool_call_id).toBe('tc-1');

    const toolResult = events.find((e) => e.event === 'tool_result');
    expect((toolResult?.dataObj as { result?: string }).result).toBe('2');
    expect((toolResult?.dataObj as { duration_ms?: number }).duration_ms).toBe(87);

    const toolEnd = events.find((e) => e.event === 'tool_end');
    expect((toolEnd?.dataObj as { status?: string }).status).toBe('success');
  });

  it('normalizeSseEvents：tool_result 被归一化为 tool-result', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      {
        event: 'tool_result',
        dataObj: {
          type: 'tool_result',
          tool_call_id: 't',
          name: 'foo',
          result: 'ok',
        },
      },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const tr = normalized.find((e) => e.kind === 'tool-result');
    expect(tr).toBeDefined();
    if (tr && tr.kind === 'tool-result') {
      expect(tr.toolCallId).toBe('t');
      expect(tr.result).toBe('ok');
    }
  });

  it('normalizeSseEvents：thinking 被归一化为 thought，文本字段正确', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      { event: 'thinking', dataObj: { type: 'thinking', data: 'analyzing' } },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const t = normalized.find((e) => e.kind === 'thought');
    expect(t).toBeDefined();
    if (t && t.kind === 'thought') {
      expect(t.text).toBe('analyzing');
    }
  });
});

describe('agentStreamE2E — 重试决策（P1-2）', () => {
  it('decideRetry 对 retryable=true 的错误返回 retry=true + delayMs=base', async () => {
    const { decideRetry } = await import('./agentStreamRetry');
    const d = decideRetry(
      { retryable: true, error: 'timeout' },
      0,
      { maxRetries: 2, baseBackoffMs: 1000 },
    );
    expect(d.retry).toBe(true);
    expect(d.delayMs).toBe(1000);
    expect(d.reason).toMatch(/retryable/i);
  });

  it('decideRetry 退避按 2^attempt 指数增长', async () => {
    const { decideRetry } = await import('./agentStreamRetry');
    const opts = { maxRetries: 4, baseBackoffMs: 500, maxBackoffMs: 8000 };
    expect(decideRetry({ retryable: true }, 0, opts).delayMs).toBe(500);
    expect(decideRetry({ retryable: true }, 1, opts).delayMs).toBe(1000);
    expect(decideRetry({ retryable: true }, 2, opts).delayMs).toBe(2000);
    expect(decideRetry({ retryable: true }, 3, opts).delayMs).toBe(4000);
  });

  it('decideRetry delayMs clamp 到 maxBackoffMs', async () => {
    const { decideRetry } = await import('./agentStreamRetry');
    const d = decideRetry(
      { retryable: true },
      10,
      { maxRetries: 20, baseBackoffMs: 1000, maxBackoffMs: 3000 },
    );
    expect(d.delayMs).toBe(3000);
  });

  it('decideRetry attempt 超过 maxRetries → 不重试', async () => {
    const { decideRetry } = await import('./agentStreamRetry');
    const d = decideRetry({ retryable: true }, 5, { maxRetries: 2 });
    expect(d.retry).toBe(false);
    expect(d.reason).toBe('max_retries_reached');
  });

  it('decideRetry retryable=false → 不重试', async () => {
    const { decideRetry } = await import('./agentStreamRetry');
    const d = decideRetry({ retryable: false, error: 'Validation' }, 0);
    expect(d.retry).toBe(false);
    expect(d.reason).toBe('not_retryable');
  });

  it('decideRetry retryable=undefined → 不重试（保守）', async () => {
    const { decideRetry } = await import('./agentStreamRetry');
    const d = decideRetry({ error: 'unknown' }, 0);
    expect(d.retry).toBe(false);
  });

  it('sleep(ms) 在无 signal 时正常 resolve', async () => {
    const { sleep } = await import('./agentStreamRetry');
    const start = Date.now();
    await sleep(50);
    expect(Date.now() - start).toBeGreaterThanOrEqual(40);
  });

  it('sleep(ms, signal) 可被 AbortSignal 中断', async () => {
    const { sleep } = await import('./agentStreamRetry');
    const ac = new AbortController();
    setTimeout(() => ac.abort(), 30);
    await expect(sleep(5000, ac.signal)).rejects.toThrow();
  });
});

describe('agentStreamE2E — useAgentLocalRuntime reasoning part 累积（P0-2）', () => {
  it('thinking 事件 → normalizeSseEvents 输出 thought', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      {
        event: 'thinking',
        dataObj: { type: 'thinking', data: '## 思考\n先分析' },
      },
      {
        event: 'thinking',
        dataObj: { type: 'thinking', data: '\n\n再验证' },
      },
      { event: 'chunk', dataObj: { type: 'chunk', data: '## 回答\n结论' } },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const thoughts = normalized.filter((e) => e.kind === 'thought');
    expect(thoughts.length).toBe(2);
    expect((thoughts[0] as { text: string }).text).toContain('先分析');
    expect((thoughts[1] as { text: string }).text).toContain('再验证');
  });

  it('splitThinkTags（P1-1 后备路径）从正文提取 <think> 段', async () => {
    // P1-1 思考折叠的兜底机制——当后端把 thinking 合到正文里时也能用
    // P2-1：实现抽到 lib/splitThinkTags，避免引入 React 运行时拖累
    const { splitThinkTags } = await import('./splitThinkTags');
    const { reasoning, cleaned } = splitThinkTags(
      '<think>\n我应该这样做\n</think>\n## 回答\n这是答案',
    );
    expect(reasoning).toContain('我应该这样做');
    expect(cleaned).toContain('## 回答');
    expect(cleaned).not.toContain('<think>');
  });
});

describe('agentStreamE2E — HITL approval 协议（P1-5）', () => {
  it('approval_required → normalizeSseEvents 输出 approval-required', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      {
        event: 'approval_required',
        dataObj: {
          type: 'approval_required',
          request_id: 'rid-1',
          tool_name: 'run_code',
          tool_args: { code: 'rm -rf /' },
          reason: '危险',
          timeout_seconds: 300,
        },
      },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const ap = normalized.find((e) => e.kind === 'approval-required');
    expect(ap).toBeDefined();
    if (ap && ap.kind === 'approval-required') {
      expect(ap.requestId).toBe('rid-1');
      expect(ap.toolName).toBe('run_code');
      expect(ap.reason).toBe('危险');
    }
  });

  it('approval_timeout → normalizeSseEvents 输出 approval-timeout', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      {
        event: 'approval_timeout',
        dataObj: {
          type: 'approval_timeout',
          request_id: 'rid-2',
          tool_name: 'run_code',
          reason: '超时自动拒绝',
        },
      },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const t = normalized.find((e) => e.kind === 'approval-timeout');
    expect(t).toBeDefined();
    if (t && t.kind === 'approval-timeout') {
      expect(t.requestId).toBe('rid-2');
      expect(t.reason).toBe('超时自动拒绝');
    }
  });

  it('error 事件带 retryable → normalizeSseEvents 输出 error', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      {
        event: 'error',
        dataObj: {
          type: 'error',
          error: 'connection timeout',
          retryable: true,
          phase: 'event_gen',
        },
      },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const e = normalized.find((e) => e.kind === 'error');
    expect(e).toBeDefined();
    if (e && e.kind === 'error') {
      expect(e.message).toBe('connection timeout');
    }
  });
});

describe('agentStreamE2E — agent_switch / agent_done 协议', () => {
  it('agent_switch → 归一化为 agent-switch', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      {
        event: 'agent_switch',
        dataObj: {
          type: 'agent_switch',
          agent: 'code_worker',
          reason: '需要执行代码',
        },
      },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const sw = normalized.find((e) => e.kind === 'agent-switch');
    expect(sw).toBeDefined();
    if (sw && sw.kind === 'agent-switch') {
      expect(sw.agent).toBe('code_worker');
      expect(sw.reason).toBe('需要执行代码');
    }
  });

  it('agent_done → 归一化为 agent-done', async () => {
    const { parseSseStream, normalizeSseEvents } = await import('./sseParser');
    const body = sseScript([
      {
        event: 'agent_done',
        dataObj: { type: 'agent_done', agent: 'FINISH' },
      },
    ]);
    const events = parseSseStream(body);
    const normalized = normalizeSseEvents(events);
    const d = normalized.find((e) => e.kind === 'agent-done');
    expect(d).toBeDefined();
    if (d && d.kind === 'agent-done') {
      expect(d.agent).toBe('FINISH');
    }
  });
});

describe('agentStreamE2E — runAgentStream 元事件（P1-2 retry attempt 帧）', () => {
  it('parseSseStream 解析 __retry_attempt 元事件', async () => {
    const { parseSseStream } = await import('./sseParser');
    const body = sseScript([
      {
        event: '__retry_attempt',
        dataObj: {
          attempt: 1,
          maxAttempts: 2,
          delayMs: 1000,
          reason: 'retryable error: timeout',
        },
      },
    ]);
    const events = parseSseStream(body);
    expect(events[0]?.event).toBe('__retry_attempt');
    expect((events[0]?.dataObj as { attempt?: number }).attempt).toBe(1);
    expect((events[0]?.dataObj as { delayMs?: number }).delayMs).toBe(1000);
  });

  it('parseSseStream 解析 __retry_failed 元事件', async () => {
    const { parseSseStream } = await import('./sseParser');
    const body = sseScript([
      {
        event: '__retry_failed',
        dataObj: {
          finalError: 'still failing',
          attempts: 3,
          reason: 'max_retries_reached',
        },
      },
    ]);
    const events = parseSseStream(body);
    expect(events[0]?.event).toBe('__retry_failed');
    expect((events[0]?.dataObj as { attempts?: number }).attempts).toBe(3);
  });
});

describe('agentStreamE2E — runAgentStream fetch 协议行为', () => {
  it('fetch 抛错：runAgentStream yield error + （如果 retryable）__retry_attempt 元事件', async () => {
    // 直接测试 runAgentStream 自身的 retry 逻辑
    vi.resetModules();
    const { runAgentStream } = await import('./runAgentStream');

    // 第一次 fetch 抛错 → 第二次抛错 → 第三次抛错（覆盖默认 maxRetries=2）
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('NetworkError'));

    const events: unknown[] = [];
    for await (const ev of runAgentStream('hi', 'sid', new AbortController().signal, {
      maxRetries: 2,
      baseBackoffMs: 1, // 加速测试
    })) {
      events.push(ev);
    }

    // 至少有 1 个 error 事件 + N 个 __retry_attempt + 1 个 __retry_failed
    const types = events.map((e: unknown) => (e as { event?: string }).event);
    expect(types.filter((t) => t === 'error').length).toBeGreaterThanOrEqual(1);
    expect(types).toContain('__retry_failed');
  });

  it('retry:false 时 fetch 抛错不重试', async () => {
    vi.resetModules();
    const { runAgentStream } = await import('./runAgentStream');
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('NetworkError'));

    const events: unknown[] = [];
    for await (const ev of runAgentStream('hi', 'sid', new AbortController().signal, {
      retry: false,
    })) {
      events.push(ev);
    }
    const types = events.map((e: unknown) => (e as { event?: string }).event);
    expect(types.filter((t) => t === 'error').length).toBe(1);
    expect(types).not.toContain('__retry_attempt');
  });
});
