/**
 * sseParser — Server-Sent Events 流式解析器（独立可测试模块）
 *
 * 与 useAgentLocalRuntime.runAgentStream 同协议的最小实现，便于单测覆盖。
 * 兼容多种后端实现：
 *   1) event 头 + data: 头 都齐全（SSE 标准）
 *   2) 只发 data: 头（部分 Python 实现）
 *   3) data: 内 JSON 串里 type 字段才是真实类型
 */

export interface SseEvent {
  /** 事件类型；data 行缺失时为 "message" */
  event: string;
  /** 原始 data 字符串 */
  data: string;
  /** 解析后的 JSON（data 不是合法 JSON 时为 null） */
  dataObj: unknown;
}

export interface SseParserOptions {
  /** 自定义 data 行解析器；默认尝试 JSON.parse */
  parseData?: (raw: string) => unknown;
}

/**
 * 把一段完整的 SSE 文本（可能含多个事件，以 \n\n 分隔）解析为事件数组。
 *
 * 重要：此函数是无状态的——不会跨调用累积 buffer，也没有任何缓存。
 * 流式 buffer 由调用方（useAgentLocalRuntime.runAgentStream）维护，
 * 这样每次新 sendMessage 都会从空 buffer 开始，杜绝「上一轮残留文本
 * 污染下一轮」的 bug。
 *
 * 用法：
 *   parseSseStream(text, { parseData: JSON.parse })
 *   → [{ event: 'chunk', data: '{"type":"chunk","data":"hello"}', dataObj: {...} }, ...]
 */
export function parseSseStream(
  rawText: string,
  opts: SseParserOptions = {},
): SseEvent[] {
  const parseData = opts.parseData ?? ((s: string) => {
    try {
      return JSON.parse(s);
    } catch {
      return null;
    }
  });

  const events: SseEvent[] = [];
  // 按 \n\n 切分；最后一段可能是不完整的事件，保留到 buffer
  const blocks = rawText.split(/\n\n/);
  for (const block of blocks) {
    const trimmed = block.replace(/\r/g, '').trim();
    if (!trimmed) continue;

    let evType = 'message';
    const dataLines: string[] = [];
    let isDoneSentinel = false;
    let commentOnly = true;
    for (const line of trimmed.split('\n')) {
      if (line.startsWith(':')) continue; // 注释行
      commentOnly = false;
      if (line.startsWith('event:')) {
        evType = line.slice(6).trim() || evType;
      } else if (line.startsWith('data:')) {
        const payload = line.slice(5).trim();
        if (payload === '[DONE]') {
          isDoneSentinel = true;
        } else if (payload) {
          dataLines.push(payload);
        }
      }
    }
    if (commentOnly) continue;
    // data:[DONE] 哨兵：保留 event 类型（end/done）作为终止帧事件，
    // 避免吞掉终止信号 → 前端 reader 关闭时机不确定 → 残余字节污染下一条消息。
    if (isDoneSentinel) {
      events.push({
        event: evType === 'message' ? 'done' : evType,
        data: '[DONE]',
        dataObj: null,
      });
      continue;
    }
    if (dataLines.length === 0) continue;

    const raw = dataLines.join('\n');
    events.push({
      event: evType,
      data: raw,
      dataObj: parseData(raw),
    });
  }
  return events;
}

/**
 * 标记 SSE 流的「终止帧」。前端收到此事件时应：
 *   1) 关闭当前 fetch/reader；
 *   2) 重置 runtime 的 buffer & isStreaming 标记；
 *   3) 不再向 Message 追加任何 text content。
 *
 * 用于兼容多种后端实现：`event: end` 头、`event: done` 头、data: [DONE] 都视为终止。
 */
export function isTerminalSseEvent(ev: SseEvent): boolean {
  if (ev.event === 'end' || ev.event === 'done') return true;
  // 某些实现把终止帧放在 data 里
  if (ev.data === '[DONE]') return true;
  const obj = (ev.dataObj ?? {}) as { type?: string };
  if (obj && (obj.type === 'end' || obj.type === 'done')) return true;
  return false;
}

/**
 * 把 SSE 事件归一化为「工具/内容事件」。
 *
 * 输入：parseSseStream 输出的原始事件
 * 输出：分类后的标准化事件，供前端 runtime 直接 yield
 *
 * 归一化规则（与 useAgentLocalRuntime.streamToChatModelResult 对齐）：
 *   chunk / token / text → text
 *   thinking             → thought（折叠显示）
 *   tool_call            → tool-call（开调用）
 *   tool_result          → tool-call（补 result）
 *   error / safety / degraded → friendly-error
 *   start / complete / end → meta（不渲染）
 */
export type NormalizedEvent =
  | { kind: 'text'; text: string }
  | { kind: 'thought'; text: string }
  | {
      kind: 'tool-call';
      toolCallId: string;
      toolName: string;
      args: Record<string, unknown>;
    }
  | { kind: 'tool-result'; toolCallId: string; result: string }
  | { kind: 'error'; message: string }
  | { kind: 'meta'; name: string }
  | {
      /** v2.2.1 — HITL 拦截：LangGraph 中断后等待人类批准 */
      kind: 'approval-required';
      requestId: string;
      toolName: string;
      toolArgs: Record<string, unknown>;
      reason: string;
    }
  | {
      /** v2.2.1 — HITL 超时：系统自动拒绝（timed_out=true） */
      kind: 'approval-timeout';
      requestId: string;
      toolName: string;
      reason: string;
    }
  | {
      /** v2.2.3 — Multi-Agent Supervisor 切到新 Worker（来自后端 SSE `event: agent_switch`） */
      kind: 'agent-switch';
      agent: string;
      reason?: string;
      requestId?: string;
    }
  | {
      /** v2.2.3 — 当前 Worker / 整轮流程结束（来自后端 SSE `event: agent_done`） */
      kind: 'agent-done';
      agent: string;
    };

export interface NormalizeOptions {
  /** 自定义 id 生成器（测试可注入） */
  genId?: () => string;
}

export function normalizeSseEvents(
  events: SseEvent[],
  opts: NormalizeOptions = {},
): NormalizedEvent[] {
  const genId = opts.genId ?? (() => Math.random().toString(36).slice(2, 10));
  const out: NormalizedEvent[] = [];

  for (const ev of events) {
    const obj = (ev.dataObj ?? {}) as Record<string, unknown>;
    const rawType = (obj.type as string | undefined) ?? ev.event;
    const t = (rawType ?? '').toLowerCase();
    const dataStr = typeof obj.data === 'string' ? obj.data : undefined;
    const contentStr = typeof obj.content === 'string' ? obj.content : undefined;

    if (t === 'chunk' || t === 'token' || t === 'text') {
      const txt = dataStr ?? contentStr ?? '';
      if (txt) out.push({ kind: 'text', text: txt });
    } else if (t === 'thinking') {
      if (dataStr) out.push({ kind: 'thought', text: dataStr });
    } else if (t === 'tool_call') {
      out.push({
        kind: 'tool-call',
        toolCallId: (obj.tool_call_id as string | undefined) ?? genId(),
        toolName: (obj.name as string | undefined) ?? dataStr ?? 'tool',
        args: (obj.args as Record<string, unknown> | undefined) ?? {},
      });
    } else if (t === 'tool_result') {
      const tcId = (obj.tool_call_id as string | undefined) ?? genId();
      out.push({
        kind: 'tool-result',
        toolCallId: tcId,
        result: (obj.result as string | undefined) ?? dataStr ?? '',
      });
    } else if (t === 'error' || t === 'safety' || t === 'degraded') {
      const msg =
        dataStr ??
        (obj.error as string | undefined) ??
        contentStr ??
        'unknown error';
      out.push({ kind: 'error', message: msg });
    } else if (t === 'start' || t === 'complete' || t === 'end') {
      out.push({ kind: 'meta', name: t });
    } else if (t === 'approval_required') {
      // v2.2.1 — HITL 拦截事件（来自 LangGraph 动态中断 + 后端 HITLStore）
      out.push({
        kind: 'approval-required',
        requestId:
          (obj.request_id as string | undefined) ??
          dataStr ??
          genId(),
        toolName: (obj.tool_name as string | undefined) ?? 'unknown_tool',
        toolArgs: (obj.tool_args as Record<string, unknown> | undefined) ?? {},
        reason: (obj.reason as string | undefined) ?? '工具需要人工批准',
      });
    } else if (t === 'approval_timeout') {
      // v2.2.1 — HITL 超时自动拒绝事件
      out.push({
        kind: 'approval-timeout',
        requestId:
          (obj.request_id as string | undefined) ??
          dataStr ??
          genId(),
        toolName: (obj.tool_name as string | undefined) ?? 'unknown_tool',
        reason:
          (obj.reason as string | undefined) ??
          '[System] Approval request timed out. Action automatically cancelled.',
      });
    } else if (t === 'agent_switch') {
      // v2.2.3 — Multi-Agent Supervisor 切到新 Worker
      const agent = (obj.agent as string | undefined) ?? dataStr ?? '';
      if (agent) {
        out.push({
          kind: 'agent-switch',
          agent,
          reason: (obj.reason as string | undefined) ?? '',
          requestId: (obj.request_id as string | undefined) ?? '',
        });
      }
    } else if (t === 'agent_done') {
      // v2.2.3 — 当前 Worker / 整轮流程结束
      const agent = (obj.agent as string | undefined) ?? 'FINISH';
      out.push({ kind: 'agent-done', agent });
    }
    // 其它类型忽略（防止不可控事件污染前端）
  }
  return out;
}

/**
 * 把技术错误信息转成对用户友好的中文文案（与 useAgentLocalRuntime.friendlyError 对齐）。
 */
export function friendlyError(raw: string | undefined): string {
  if (!raw) return '请求失败：未知错误';
  const lower = raw.toLowerCase();
  // 顺序：先检查 placeholder（避免 "placeholder api key" 被 "api key" 分支抢走）
  if (lower.includes('placeholder')) {
    return '⚠️ 仍在使用占位 API Key，请在 .env 中填写真实 Key 后重启后端。';
  }
  if (lower.includes('timeout') || lower.includes('timed out')) {
    return '⏱️ 请求超时：本地 Ollama 模型可能还在生成中，请稍后再试，或在 Tools 页切换更快的模型。';
  }
  if (lower.includes('api key') || lower.includes('unauthorized') || lower.includes('401')) {
    return '🔑 API Key 无效或未配置：请到 Tools 页检查 provider 配置。';
  }
  if (lower.includes('connect') || lower.includes('econnrefused')) {
    return '🔌 连接失败：本地 Ollama 可能未启动，请运行 `ollama serve` 后重试。';
  }
  return `⚠️ ${raw}`;
}
