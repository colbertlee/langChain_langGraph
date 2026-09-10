import { describe, it, expect } from 'vitest';
import {
  parseSseStream,
  normalizeSseEvents,
  isTerminalSseEvent,
  friendlyError,
} from './sseParser';

describe('parseSseStream', () => {
  it('解析标准 SSE：event + data 多行', () => {
    const raw = [
      'event: chunk',
      'data: {"type":"chunk","data":"hello "}',
      '',
      'event: chunk',
      'data: {"type":"chunk","data":"world"}',
      '',
      '',
    ].join('\n');
    const events = parseSseStream(raw);
    expect(events).toHaveLength(2);
    expect(events[0].event).toBe('chunk');
    expect(events[0].dataObj).toEqual({ type: 'chunk', data: 'hello ' });
    expect(events[1].dataObj).toEqual({ type: 'chunk', data: 'world' });
  });

  it('支持只有 data 行（无 event 头）', () => {
    const raw = [
      'data: {"type":"thinking","data":"reasoning..."}',
      '',
    ].join('\n');
    const events = parseSseStream(raw);
    expect(events).toHaveLength(1);
    expect(events[0].event).toBe('message');
    expect(events[0].dataObj).toEqual({ type: 'thinking', data: 'reasoning...' });
  });

  it('忽略注释行（以 : 开头）', () => {
    const raw = [
      ': this is a comment',
      'event: chunk',
      'data: x',
      '',
    ].join('\n');
    const events = parseSseStream(raw);
    expect(events).toHaveLength(1);
  });

  it('data: [DONE] 被忽略', () => {
    const raw = [
      'data: {"type":"chunk","data":"hi"}',
      '',
      'data: [DONE]',
      '',
    ].join('\n');
    const events = parseSseStream(raw);
    // v2.0.11：[DONE] 哨兵不再被静默丢弃 —— 它必须作为 done 事件输出，
    // 让前端 reader 知道可以安全关闭。否则流残余字节会泄到下一条 sendMessage。
    expect(events).toHaveLength(2);
    expect(events[0].data).toBe('{"type":"chunk","data":"hi"}');
    expect(events[1].event).toBe('done');
    expect(events[1].data).toBe('[DONE]');
  });

  it('多个 data: 行被 join 为 \\n', () => {
    const raw = [
      'data: line1',
      'data: line2',
      '',
    ].join('\n');
    const events = parseSseStream(raw);
    expect(events).toHaveLength(1);
    expect(events[0].data).toBe('line1\nline2');
  });

  it('非 JSON data → dataObj=null', () => {
    const raw = ['data: raw text', '', ''].join('\n');
    const events = parseSseStream(raw);
    expect(events).toHaveLength(1);
    expect(events[0].dataObj).toBeNull();
  });

  it('空字符串返回空数组', () => {
    expect(parseSseStream('')).toEqual([]);
    expect(parseSseStream('   ')).toEqual([]);
  });
});

describe('normalizeSseEvents', () => {
  it('chunk → text', () => {
    const events = parseSseStream('data: {"type":"chunk","data":"hi"}\n\n');
    const norm = normalizeSseEvents(events);
    expect(norm).toEqual([{ kind: 'text', text: 'hi' }]);
  });

  it('thinking → thought（折叠）', () => {
    const events = parseSseStream(
      'data: {"type":"thinking","data":"because..."}\n\n',
    );
    const norm = normalizeSseEvents(events);
    expect(norm).toEqual([{ kind: 'thought', text: 'because...' }]);
  });

  it('tool_call → tool-call（带 args/toolCallId）', () => {
    const events = parseSseStream(
      'data: {"type":"tool_call","tool_call_id":"tc-1","name":"bash","args":{"subcommand":"ls"}}\n\n',
    );
    const norm = normalizeSseEvents(events);
    expect(norm[0]).toEqual({
      kind: 'tool-call',
      toolCallId: 'tc-1',
      toolName: 'bash',
      args: { subcommand: 'ls' },
    });
  });

  it('tool_call 无 tool_call_id 时生成 fallback id', () => {
    const events = parseSseStream(
      'data: {"type":"tool_call","name":"x"}\n\n',
    );
    const norm = normalizeSseEvents(events, { genId: () => 'fixed-id' });
    expect(norm[0]).toMatchObject({ kind: 'tool-call', toolCallId: 'fixed-id' });
  });

  it('tool_result → tool-result（带 result）', () => {
    const events = parseSseStream(
      'data: {"type":"tool_result","tool_call_id":"tc-1","result":"done"}\n\n',
    );
    const norm = normalizeSseEvents(events);
    expect(norm).toEqual([
      { kind: 'tool-result', toolCallId: 'tc-1', result: 'done' },
    ]);
  });

  it('error / safety / degraded → error', () => {
    for (const t of ['error', 'safety', 'degraded']) {
      const events = parseSseStream(
        `data: {"type":"${t}","data":"oops"}\n\n`,
      );
      const norm = normalizeSseEvents(events);
      expect(norm).toEqual([{ kind: 'error', message: 'oops' }]);
    }
  });

  it('start / complete / end → meta', () => {
    const events = parseSseStream(
      [
        'data: {"type":"start"}\n\n',
        'data: {"type":"complete"}\n\n',
        'data: {"type":"end"}\n\n',
      ].join(''),
    );
    const norm = normalizeSseEvents(events);
    expect(norm.map((e) => (e as { name: string }).name)).toEqual([
      'start',
      'complete',
      'end',
    ]);
  });

  it('从 SSE event 头读取 type（兼容旧后端）', () => {
    const events = parseSseStream(
      'event: chunk\ndata: {"data":"abc"}\n\n',
    );
    // 这里 data 里没有 type，但 event 头是 "chunk" → 应归一化为 text
    const norm = normalizeSseEvents(events);
    expect(norm).toEqual([{ kind: 'text', text: 'abc' }]);
  });

  it('空 data 字符串不会生成 text', () => {
    const events = parseSseStream('data: {"type":"chunk","data":""}\n\n');
    const norm = normalizeSseEvents(events);
    expect(norm).toEqual([]);
  });
});

describe('friendlyError', () => {
  it('timeout', () => {
    expect(friendlyError('Request timeout')).toMatch(/超时/);
  });
  it('401 / api key', () => {
    expect(friendlyError('HTTP 401 unauthorized')).toMatch(/API Key/);
  });
  it('connection refused', () => {
    expect(friendlyError('ECONNREFUSED')).toMatch(/连接失败/);
  });
  it('placeholder', () => {
    expect(friendlyError('using placeholder api key')).toMatch(/占位/);
  });
  it('未知错误兜底', () => {
    expect(friendlyError('something weird')).toMatch(/⚠️/);
  });
  it('空值', () => {
    expect(friendlyError(undefined)).toMatch(/未知错误/);
  });
});

describe('isTerminalSseEvent (回归测试：end 帧识别)', () => {
  it('event:end 头视为终止', () => {
    expect(isTerminalSseEvent({ event: 'end', data: '{}', dataObj: {} })).toBe(true);
    expect(isTerminalSseEvent({ event: 'done', data: '{}', dataObj: {} })).toBe(true);
  });

  it('data:[DONE] 视为终止', () => {
    expect(
      isTerminalSseEvent({ event: 'message', data: '[DONE]', dataObj: null }),
    ).toBe(true);
  });

  it('data 内 JSON type=end 视为终止', () => {
    expect(
      isTerminalSseEvent({
        event: 'message',
        data: '{"type":"end"}',
        dataObj: { type: 'end' },
      }),
    ).toBe(true);
  });

  it('普通 chunk 不应视为终止', () => {
    expect(
      isTerminalSseEvent({
        event: 'message',
        data: '{"type":"chunk","data":"hello"}',
        dataObj: { type: 'chunk', data: 'hello' },
      }),
    ).toBe(false);
  });
});

/**
 * 回归测试 —— 「连续两条指令，第二条不包含第一条的文本」
 *
 * 这个测试描述了实际 bug 的根因与修复：
 * 旧实现里 runAgentStream 共享一个 buffer（或 reader），第一轮没读完的
 * chunk 会被第二轮继承。新实现里：
 *   - parseSseStream 是无状态的，每次调用只处理传入的字符串
 *   - 调用方（runAgentStream）维护自己的 buffer；新一次 sendMessage
 *     会创建新的 generator / 新的 buffer / 新的 reader
 *
 * 这里直接验证 parseSseStream 不携带跨调用的状态：
 */
describe('parseSseStream 跨调用隔离 (回归)', () => {
  it('连续两次调用不会互相污染', () => {
    // 第一轮的「上一轮 AI Agent 长篇回答」
    // 注意：每个事件块结尾必须以 \n\n 结束，与 SSE 协议一致。
    const firstRound = [
      'event: chunk',
      'data: {"type":"chunk","data":"AI Agent 是新一代人工智能代理..."}',
      '',
      'event: end',
      'data: [DONE]',
      '',
      '',
    ].join('\n');

    // 第二轮的「记住我的幸运数字」
    const secondRound = [
      'event: chunk',
      'data: {"type":"chunk","data":"好的，已记住你的幸运数字是 888。"}',
      '',
      'event: end',
      'data: [DONE]',
      '',
      '',
    ].join('\n');

    // 关键断言：模拟「上一轮 buffer 残留 + 新一轮 chunks」的拼接场景
    // —— parseSseStream 应该如实解析所有事件（不会主动"清空"）。
    // 但调用方在每次 sendMessage 时会创建新的 buffer，所以「第一轮的
    // chunk 不会进入第二轮」。这里验证 parseSseStream 的解析行为一致：
    const corrupted = firstRound + secondRound;
    const allEvents = parseSseStream(corrupted);
    const textChunks = allEvents
      .map((ev) => {
        const obj = (ev.dataObj ?? {}) as { type?: string; data?: string };
        return obj.type === 'chunk' && typeof obj.data === 'string' ? obj.data : '';
      })
      .filter(Boolean);
    expect(textChunks).toEqual([
      'AI Agent 是新一代人工智能代理...',
      '好的，已记住你的幸运数字是 888。',
    ]);

    // 第二轮开始前的残留：模拟"新一次 sendMessage 拿到独立的空 buffer"，
    // parseSseStream 只解析传入的字符串，所以第二轮单独解析时绝对不会
    // 出现第一条文本。
    // ⚠️ 真实流式场景下，每次 sendMessage 都会创建新的 buffer，第一条
    // 流的残余字节根本不会进入第二轮。这里直接验证 parseSseStream
    // 对独立字符串的解析行为。
    const secondOnlyEvents = parseSseStream(secondRound);
    const secondTexts = secondOnlyEvents
      .map((ev) => {
        const obj = (ev.dataObj ?? {}) as { type?: string; data?: string };
        return obj.type === 'chunk' && typeof obj.data === 'string' ? obj.data : '';
      })
      .filter(Boolean);
    expect(secondTexts).toHaveLength(1);
    expect(secondTexts[0]).toBe('好的，已记住你的幸运数字是 888。');
    expect(secondTexts.join('')).not.toContain('AI Agent');

    // 终止帧必须能被识别（防 reader 不关 → 残余字节污染下一条 sendMessage）
    const endEvents = allEvents.filter((ev) => ev.event === 'end');
    expect(endEvents.length).toBe(2);
  });

  it('data 中的 \\n 不会被抹除（Markdown 表格行保护）', () => {
    const raw = [
      'event: chunk',
      'data: {"type":"chunk","data":"| 列1 | 列2 |\\n|---|---|Marcus|\\n| a | b |"}',
      '',
      '',
    ].join('\n');
    const events = parseSseStream(raw);
    expect(events).toHaveLength(1);
    const obj = (events[0].dataObj ?? {}) as { type?: string; data?: string };
    expect(obj.type).toBe('chunk');
    // 关键的回归断言：表格内的换行必须保留，否则 MarkdownText 渲染时
    // 会把所有行塌成一行
    expect(obj.data).toContain('\n');
    expect(obj.data?.split('\n').length).toBe(3);
  });
});
