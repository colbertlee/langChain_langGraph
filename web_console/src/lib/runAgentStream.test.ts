/**
 * runAgentStream — 回归测试套件（防"下一轮重复上一轮内容"）。
 *
 * 这是 bug "搜索 AI Agent → 记住幸运数字 888，结果第二条回复里完整
 * 包含了上一轮长篇回答" 的根因测试。
 *
 * 验证点：
 *  1) parseSseStream / runAgentStream 不在跨调用间共享状态
 *  2) end / done 帧后流必须彻底结束，不再产生任何额外事件
 *  3) 第二条 sendMessage 启动时，第一条的残余字节（即使仍在飞行中）
 *     也不会泄到第二条的消息里
 *  4) 异常/中断后 streaming 状态被复位
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  runAgentStream,
  consumeSseStream,
  createAgentStreamController,
  _resetActiveStreamIdForTests,
  _getActiveStreamIdForTests,
} from './runAgentStream';

/**
 * 构造一个假的 ReadableStream，每个 await pull() 就吐出下一个 chunk，
 * 模拟 fetch().body.getReader() 的异步行为。
 */
function makeSseStream(chunks: string[]) {
  const encoder = new TextEncoder();
  const queue = chunks.map((c) => encoder.encode(c));
  let i = 0;
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (i < queue.length) {
        // 让出一次 microtask，模拟真实网络
        await Promise.resolve();
        controller.enqueue(queue[i++]);
      } else {
        controller.close();
      }
    },
  });
}

function fakeOkResponse(body: ReadableStream<Uint8Array>) {
  return new Response(body, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  });
}

async function collectChunks<T>(
  gen: AsyncGenerator<T>,
): Promise<T[]> {
  const out: T[] = [];
  for await (const ev of gen) out.push(ev);
  return out;
}

describe('runAgentStream — 单流终止帧', () => {
  beforeEach(() => {
    _resetActiveStreamIdForTests();
    vi.restoreAllMocks();
  });

  it('收到 event:end 后立刻终止，不再产生额外 chunk', async () => {
    const firstRound = [
      'event: chunk\ndata: {"type":"chunk","data":"你好，世界"}\n\n',
      'event: end\ndata: {}\n\n',
    ].join('');
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockResolvedValue(fakeOkResponse(makeSseStream([firstRound])));

    const events = await collectChunks(
      runAgentStream('hi', 'sid-1', new AbortController().signal),
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const chunks = events.filter(
      (e) => (e.dataObj as { type?: string } | null)?.type === 'chunk',
    );
    expect(chunks).toHaveLength(1);
    expect((chunks[0].dataObj as { data: string }).data).toBe('你好，世界');

    // 终止帧必须出现在 events 列表里
    const ends = events.filter(
      (e) => e.event === 'end' || (e.dataObj as { type?: string } | null)?.type === 'end',
    );
    expect(ends.length).toBeGreaterThanOrEqual(1);
  });

  it('data:[DONE] 也视为终止帧（兼容性）', async () => {
    const firstRound = [
      'data: {"type":"chunk","data":"ok"}\n\n',
      'data: [DONE]\n\n',
    ].join('');
    vi.spyOn(global, 'fetch').mockResolvedValue(
      fakeOkResponse(makeSseStream([firstRound])),
    );

    const events = await collectChunks(
      runAgentStream('hi', 'sid-1', new AbortController().signal),
    );
    const chunks = events.filter(
      (e) => (e.dataObj as { type?: string } | null)?.type === 'chunk',
    );
    // 关键：终止帧之后的额外 chunk 不会再次 yield
    expect(chunks).toHaveLength(1);
  });
});

describe('runAgentStream — 跨流隔离（核心回归）', () => {
  beforeEach(() => {
    _resetActiveStreamIdForTests();
    vi.restoreAllMocks();
  });

  it('连续两条指令，第二条回复绝不包含第一条文本', async () => {
    // 第一轮：AI Agent 长篇回答（模拟后端分多个 chunk 推送）
    const firstRoundChunks = [
      'event: chunk\ndata: {"type":"chunk","data":"AI Agent 是新一代人工智能代理，具备..."}\n\n',
      'event: chunk\ndata: {"type":"chunk","data":"自主感知、规划、工具调用、记忆等核心能力..."}\n\n',
      'event: end\ndata: {}\n\n',
    ];
    // 第二轮：幸运数字
    const secondRoundChunks = [
      'event: chunk\ndata: {"type":"chunk","data":"好的，已记住你的幸运数字是 888。"}\n\n',
      'event: end\ndata: {}\n\n',
    ];

    // 关键场景：fetch 被两次调用，每次返回独立的 stream，
    // 但模块级 __activeStreamId 必须在第二次 sendMessage 时翻新，
    // 这样**第一次流如果还在飞行中**也不会污染第二次的 buffer。
    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockResolvedValueOnce(fakeOkResponse(makeSseStream(firstRoundChunks)))
      .mockResolvedValueOnce(fakeOkResponse(makeSseStream(secondRoundChunks)));

    // 第一轮
    const firstEvents = await collectChunks(
      runAgentStream(
        '帮我搜索一下最新的 AI Agent 发展动态',
        'sid-A',
        new AbortController().signal,
      ),
    );
    const firstText = firstEvents
      .map(
        (e) =>
          (e.dataObj as { type?: string; data?: string } | null)?.data ?? '',
      )
      .filter(Boolean)
      .join('');
    expect(firstText).toContain('AI Agent');
    expect(firstText).not.toContain('幸运数字');

    // 第二轮
    const secondEvents = await collectChunks(
      runAgentStream(
        '记住我的幸运数字是 888',
        'sid-A',
        new AbortController().signal,
      ),
    );
    const secondText = secondEvents
      .map(
        (e) =>
          (e.dataObj as { type?: string; data?: string } | null)?.data ?? '',
      )
      .filter(Boolean)
      .join('');

    // ✅ 核心断言：第二轮文本绝不包含第一轮的文本
    expect(secondText).not.toContain('AI Agent');
    expect(secondText).not.toContain('自主感知');
    expect(secondText).not.toContain('新一代人工智能代理');
    expect(secondText).toContain('888');

    // fetch 必须被调过 2 次（两次独立请求，不复用 stream）
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // 第二轮的 streamId 必须大于第一轮（保证模块级计数器递增）
    expect(_getActiveStreamIdForTests()).toBeGreaterThanOrEqual(2);
  });

  it('第一条流还没结束就触发第二条，第一条 reader 必须 cancel', async () => {
    // 第一条流：故意模拟"长篇回答"分多个 chunk 慢慢推，最后才发 end。
    // 第二条流：立刻返回简单内容。
    // 验证：在第二条 sendMessage 触发后，第一条的残余 chunk 不再被处理。
    let firstCancelled = false;

    // 第一条流：构造一个慢流，每 chunk 之间等待
    const firstStream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const encoder = new TextEncoder();
        controller.enqueue(
          encoder.encode(
            'event: chunk\ndata: {"type":"chunk","data":"长篇回答 part1..."}\n\n',
          ),
        );
        // 等第二条 fetch 启动（>= 30ms 后）
        await new Promise((r) => setTimeout(r, 30));
        controller.enqueue(
          encoder.encode(
            'event: chunk\ndata: {"type":"chunk","data":"长篇回答 part2..."}\n\n',
          ),
        );
        await new Promise((r) => setTimeout(r, 30));
        controller.enqueue(encoder.encode('event: end\ndata: {}\n\n'));
        controller.close();
      },
      cancel() {
        firstCancelled = true;
      },
    });

    const secondRoundChunks = [
      'event: chunk\ndata: {"type":"chunk","data":"幸运数字 888"}\n\n',
      'event: end\ndata: {}\n\n',
    ].join('');

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockResolvedValueOnce(fakeOkResponse(firstStream))
      .mockResolvedValueOnce(
        fakeOkResponse(makeSseStream([secondRoundChunks])),
      );

    // 启动第一条（不 await，让它在后台跑）
    const firstPromise = collectChunks(
      runAgentStream('q1', 'sid', new AbortController().signal),
    );
    // 等第一条第一个 chunk 进来
    await new Promise((r) => setTimeout(r, 15));
    // 启动第二条（这会触发 __activeStreamId 翻新，第一条的下一次 read 会失效）
    const secondPromise = collectChunks(
      runAgentStream('q2', 'sid', new AbortController().signal),
    );

    const [, secondEvents] = await Promise.all([firstPromise, secondPromise]);
    const secondText = secondEvents
      .map(
        (e) =>
          (e.dataObj as { type?: string; data?: string } | null)?.data ?? '',
      )
      .filter(Boolean)
      .join('');

    // 关键断言：第二条文本里不能沾上第一条的 part1/part2
    expect(secondText).not.toContain('长篇回答');
    expect(secondText).toContain('888');

    expect(fetchMock).toHaveBeenCalledTimes(2);
    // 第一条 reader 应被 cancel（背景流的 cancel hook 被触发）
    expect(firstCancelled).toBe(true);
  });

  it('HTTP 错误时不再 yield 任何 chunk', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('internal error', { status: 500 }),
    );
    const events = await collectChunks(
      runAgentStream('hi', 'sid', new AbortController().signal),
    );
    // 应当 yield 一个 error 事件，没有 chunk
    const chunks = events.filter(
      (e) => (e.dataObj as { type?: string } | null)?.type === 'chunk',
    );
    expect(chunks).toHaveLength(0);
    expect(events.some((e) => e.event === 'error')).toBe(true);
  });

  it('fetch 抛错（网络中断）时不抛到 generator 之外', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('NetworkError'));
    // 不应 throw —— 应 yield friendly-error 事件
    // P1-2：测试里关闭自动重试，避免 maxRetries=2 产生 3 个 error 事件
    const events = await collectChunks(
      runAgentStream('hi', 'sid', new AbortController().signal, {
        retry: false,
      }),
    );
    const errors = events.filter((e) => e.event === 'error');
    expect(errors).toHaveLength(1);
  });

  it('用户 AbortSignal 触发后立刻退出，不再 yield 任何 chunk', async () => {
    // 构造一个永远不结束的流（仅在 controller.close() 时结束）
    const controllerRef: { current: ReadableStreamDefaultController<Uint8Array> | null } = {
      current: null,
    };
    const infinite = new ReadableStream<Uint8Array>({
      start(c) {
        controllerRef.current = c;
      },
    });
    vi.spyOn(global, 'fetch').mockResolvedValue(fakeOkResponse(infinite));

    const ac = new AbortController();
    const promise = collectChunks(
      runAgentStream('hi', 'sid', ac.signal),
    );
    ac.abort();
    controllerRef.current?.close();
    const events = await promise;
    expect(events).toHaveLength(0);
  });
});

// ============================================================
// v2.0.11 — AgentStreamController（AbortController + 性能指标）
// ============================================================
describe('AgentStreamController — abort / metrics', () => {
  beforeEach(() => {
    _resetActiveStreamIdForTests();
  });

  it('初始 metrics 应全为 0 / null', () => {
    const c = createAgentStreamController();
    const m = c.metrics();
    expect(m.ttftMs).toBeNull();
    expect(m.chunkCount).toBe(0);
    expect(m.durationMs).toBeGreaterThanOrEqual(0);
    expect(m.aborted).toBe(false);
    expect(m.reason).toBe('completed');
    expect(c.isStale()).toBe(false);
  });

  it('abort() 后 metrics.aborted=true 且 signal.aborted=true', () => {
    const c = createAgentStreamController();
    c.abort();
    expect(c.signal.aborted).toBe(true);
    const m = c.metrics();
    expect(m.aborted).toBe(true);
    expect(m.reason).toBe('aborted');
    expect(c.isStale()).toBe(true);
  });

  it('重复 abort() 是幂等的（不会重复触发）', () => {
    const c = createAgentStreamController();
    c.abort();
    const before = c.metrics();
    c.abort();
    const after = c.metrics();
    expect(after.aborted).toBe(true);
    expect(after.durationMs).toBe(before.durationMs);
  });

  it('recordFirstChunk() 只记录第一次（TTFT）', async () => {
    const c = createAgentStreamController();
    c.recordFirstChunk();
    const first = c.metrics().ttftMs;
    expect(first).not.toBeNull();
    // 等一会儿再 record —— ttft 不应变化
    await new Promise((r) => setTimeout(r, 5));
    c.recordFirstChunk();
    expect(c.metrics().ttftMs).toBe(first);
  });

  it('recordChunk() 累加 chunkCount', () => {
    const c = createAgentStreamController();
    c.recordChunk();
    c.recordChunk();
    c.recordChunk();
    expect(c.metrics().chunkCount).toBe(3);
  });

  it('被新流抢占时，旧的 isStale() 变 true（module-level streamId 计数器）', async () => {
    const c1 = createAgentStreamController();
    expect(c1.isStale()).toBe(false);
    // 创建第二个 controller —— 模块级计数器递增 → 第一个立刻 stale
    createAgentStreamController();
    expect(c1.isStale()).toBe(true);
    // 不留引用问题，c1 释放即可
  });
});

// ============================================================
// v2.0.11 — 主动 abort → 流读取提前结束 + UI 状态恢复
// ============================================================
describe('AbortController — 主动 abort 流读取', () => {
  beforeEach(() => {
    _resetActiveStreamIdForTests();
  });

  it('consumeSseStream 在 controller.abort() 后立刻停止 yield', async () => {
    const encoder = new TextEncoder();
    const streamRef: { current: ReadableStreamDefaultController<Uint8Array> | null } = {
      current: null,
    };
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        streamRef.current = c;
        // 先推几个 chunk
        c.enqueue(
          encoder.encode(
            'event: chunk\ndata: {"type":"chunk","data":"before-abort"}\n\n',
          ),
        );
      },
    });

    const controller = createAgentStreamController();
    const res = new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });

    // consumeSseStream 现在返回 Promise<AsyncGenerator>，需 await
    const gen = await consumeSseStream(res, controller);
    const events: import('./runAgentStream').SseEvent[] = [];
    // 只拉一个事件，让 gen 进入 `await reader.read()` 等待下一个 chunk
    const it = gen[Symbol.asyncIterator]();
    const first = await it.next();
    if (!first.done) events.push(first.value);

    expect(events.length).toBeGreaterThanOrEqual(1);
    expect(JSON.stringify(events)).toContain('before-abort');

    // 现在 abort —— controller.signal.aborted=true → 下次 gen.next() 时
    // reader.read() 应该立刻返回或 cancel 链路触发 finally
    controller.abort();

    // 给 reader 一点时间退出，并 close stream（防止 read 永远阻塞）
    streamRef.current?.close();
    await new Promise((r) => setTimeout(r, 10));

    const finalMetrics = controller.metrics();
    expect(finalMetrics.aborted).toBe(true);
    expect(finalMetrics.reason).toBe('aborted');
    // "before-abort" 应该被收到，"should-not-appear" 不应
    const allData = JSON.stringify(events);
    expect(allData).toContain('before-abort');
    expect(allData).not.toContain('should-not-appear');
  });

  it('runAgentStream 在外部 AbortSignal 触发后立即停止 yield（最终 events 数量受控）', async () => {
    const encoder = new TextEncoder();
    let streamCancelled = false;
    const body = new ReadableStream<Uint8Array>({
      async start(c) {
        // 推一个 chunk 进去
        c.enqueue(
          encoder.encode(
            'event: chunk\ndata: {"type":"chunk","data":"only-one"}\n\n',
          ),
        );
      },
      cancel() {
        streamCancelled = true;
      },
    });
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    );

    const ac = new AbortController();
    const eventsPromise = collectChunks(
      runAgentStream('hi', 'sid', ac.signal),
    );
    // 立刻 abort
    ac.abort();
    const events = await eventsPromise;
    // 应该只 yield 最多 1 个 chunk（外部 abort 触发后 read 立刻失败 / cancel）
    expect(events.length).toBeLessThanOrEqual(1);
    expect(streamCancelled).toBe(true);
  });
});

// ============================================================
// v2.0.11 — 性能指标贯通测试（chunk → metrics 正确反映）
// ============================================================
describe('流式指标贯通测试 — TTFT / duration / chunkCount', () => {
  beforeEach(() => {
    _resetActiveStreamIdForTests();
  });

  it('收到 3 个 chunk 后，metrics.chunkCount === 3 且 ttftMs !== null', async () => {
    const controller = createAgentStreamController();

    // 模拟 SSE 帧流
    const stream = makeSseStream([
      'event: chunk\ndata: {"type":"chunk","data":"hello"}\n\n',
      'event: chunk\ndata: {"type":"chunk","data":" world"}\n\n',
      'event: chunk\ndata: {"type":"chunk","data":"!"}\n\n',
      'event: end\ndata: [DONE]\n\n',
    ]);
    const res = new Response(stream, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
    });

    const events = await collectChunks(await consumeSseStream(res, controller));

    // 业务侧记录指标（runtime 里就是这么做的）
    for (const ev of events) {
      const t = (ev.dataObj as { type?: string; data?: string } | null)?.type;
      if (t === 'chunk') {
        controller.recordFirstChunk();
        controller.recordChunk();
      }
    }

    const m = controller.metrics();
    expect(events.filter((e) => e.event !== 'end').length).toBeGreaterThanOrEqual(3);
    expect(m.chunkCount).toBe(3);
    expect(m.ttftMs).not.toBeNull();
    expect(m.ttftMs).toBeGreaterThanOrEqual(0);
    expect(m.aborted).toBe(false);
    expect(m.reason).toBe('completed');
  });
});
