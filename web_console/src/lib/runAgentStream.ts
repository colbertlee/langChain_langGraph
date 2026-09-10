/**
 * runAgentStream — SSE 流式读取器 + 流控制器 + 性能指标 + 自动重试
 *
 * v2.0.11 增强：
 *  - 引入 AgentStreamController 工厂，把 AbortController / 流 id / 性能指标
 *    集中管理，避免在多处隐性共享 mutable state。
 *  - 性能指标：
 *      * ttftMs   —— Time To First Token（首字延迟），从 fetch 开始到第一个 chunk 抵达
 *      * durationMs —— 总流式耗时（fetch 开始 → 终止帧 / abort）
 *      * chunkCount —— 接收到的 chunk 帧数（不计 start/end/error）
 *      * aborted   —— 用户是否主动 abort
 *  - abort() 触发的清理：reader.cancel() + 清空内部 buffer，确保残余字节
 *    不会泄到下一轮 sendMessage。
 *  - parseSseStream 仍是无状态的纯函数。
 *
 * v2.4 — P1-2 自动重试：
 *  - 后端 `event_gen` 异常分支 / 流静默断开时 yield `{type:"error", retryable:bool}`。
 *  - 本模块捕获到 retryable=true 时，指数退避后自动重新发起一次 POST：
 *      - 最多 2 次重试（attempt 0 = 首次；最多 2 次失败后放弃）
 *      - 退避 1s → 2s → 4s（clamp 到 8s）
 *      - 重试过程中 yield 元事件 `__retry_attempt` / `__retry_failed`，便于 UI 渲染
 *  - 用户主动 abort 立即退出，不重试。
 *  - 旧测试用 `runAgentStream(text, sid, signal)` 的 3 参签名仍兼容；
 *    新代码建议传第 4 个 `{ retry?: false }` 来关掉重试（测试用）。
 */
import {
  parseSseStream,
  isTerminalSseEvent,
  friendlyError as sharedFriendlyError,
  type SseEvent,
} from './sseParser';
import {
  decideRetry,
  sleep,
  DEFAULT_RETRY_OPTIONS,
  type RetryOptions,
} from './agentStreamRetry';

let __activeStreamId = 0;
function __nextStreamId(): number {
  __activeStreamId += 1;
  return __activeStreamId;
}

export function _resetActiveStreamIdForTests(): void {
  __activeStreamId = 0;
}

export function _getActiveStreamIdForTests(): number {
  return __activeStreamId;
}

/**
 * 流性能指标（开发模式 UI 用，生产不渲染）。
 */
export interface StreamMetrics {
  /** TTFT（Time To First Token），毫秒。null 表示没有收到任何 chunk。 */
  ttftMs: number | null;
  /** 总流式耗时（fetch 开始 → 终止/abort），毫秒 */
  durationMs: number;
  /** 收到的 chunk 帧数（不含 start/end/error/meta） */
  chunkCount: number;
  /** 是否被用户主动 abort */
  aborted: boolean;
  /** 终止原因标签，便于 UI 展示 */
  reason: 'completed' | 'aborted' | 'error' | 'stale';
}

/**
 * 流控制器：
 *  - abort()       立刻触发 abort 信号 → reader.cancel() → 清空 buffer
 *  - metrics()     返回当前指标的不可变快照
 *  - isStale()     判断是否被新流抢占（模块级 __activeStreamId）
 *  - signal        透传给 fetch 的 AbortSignal
 *  - streamId      内部流 id（debug / 测试可见）
 */
export interface AgentStreamController {
  readonly signal: AbortSignal;
  readonly streamId: number;
  abort(): void;
  isStale(): boolean;
  metrics(): StreamMetrics;
  /** 在收到首个 chunk 时调用一次，用于记录 TTFT */
  recordFirstChunk(): void;
  /** 在收到任意 chunk 时调用一次（用于 chunkCount 统计） */
  recordChunk(): void;
}

export function createAgentStreamController(): AgentStreamController {
  const ac = new AbortController();
  const streamId = __nextStreamId();
  const start = performance.now();
  const m: StreamMetrics = {
    ttftMs: null,
    durationMs: 0,
    chunkCount: 0,
    aborted: false,
    reason: 'completed',
  };

  return {
    signal: ac.signal,
    streamId,
    abort() {
      if (!ac.signal.aborted) {
        m.aborted = true;
        m.reason = 'aborted';
        m.durationMs = performance.now() - start;
        ac.abort();
      }
    },
    isStale() {
      return __activeStreamId !== streamId || ac.signal.aborted;
    },
    metrics() {
      // 每次返回不可变快照
      return {
        ttftMs: m.ttftMs,
        durationMs:
          m.durationMs > 0 ? m.durationMs : performance.now() - start,
        chunkCount: m.chunkCount,
        aborted: m.aborted,
        reason: m.reason,
      };
    },
    recordFirstChunk() {
      if (m.ttftMs === null) {
        m.ttftMs = performance.now() - start;
      }
    },
    recordChunk() {
      m.chunkCount += 1;
    },
  };
}

/**
 * 把一个 fetch 的 Response body 解析为 SSE 事件流，并 attach 到 controller。
 * 与旧 consumeSseStream 等价，但把 AbortSignal / 流 id / metrics 委托给
 * controller 统一管理，避免外部再持有 mutable state。
 */
export async function consumeSseStream(
  res: Response,
  controller: AgentStreamController,
): Promise<AsyncGenerator<SseEvent, void, void>> {
  if (!res.body) {
    async function* empty() {
      yield {
        event: 'error',
        data: sharedFriendlyError('Empty response from server'),
        dataObj: null,
      } satisfies SseEvent;
    }
    return empty();
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  async function* gen() {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        if (controller.isStale()) {
          buffer = '';
          try {
            await reader.cancel();
          } catch {
            /* ignore */
          }
          return;
        }

        buffer += decoder.decode(value, { stream: true });
        const events = parseSseStream(buffer);
        const lastSep = buffer.lastIndexOf('\n\n');
        if (lastSep >= 0) buffer = buffer.slice(lastSep + 2);
        for (const ev of events) {
          yield ev;
          if (isTerminalSseEvent(ev)) {
            buffer = '';
            try {
              await reader.cancel();
            } catch {
              /* ignore */
            }
            return;
          }
        }

        if (controller.isStale()) {
          buffer = '';
          try {
            await reader.cancel();
          } catch {
            /* ignore */
          }
          return;
        }
      }
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') return;
      buffer = '';
    } finally {
      try {
        if (!controller.isStale()) await reader.cancel();
      } catch {
        /* ignore */
      }
    }
  }

  return gen();
}

/**
 * 启动一次新的 SSE 流（带 P1-2 自动重试）。
 *
 * 注意：每个 runAgentStream 调用必须传入一个**独立**的 controller。
 * 调用方（runtime / store）负责：1) 创建 controller 2) 调 abort() / 3) 读 metrics。
 *
 * P1-2 行为：
 *  - 第一次 fetch → 拿到流 → 如果遇到 retryable=true 的 error（来自后端 event_gen
 *    的异常分支，或流静默断开），自动 sleep backoff 后重试；
 *  - 最多 2 次重试（opts.maxRetries 默认 2）；
 *  - 重试期间 yield 元事件（event: '__retry_attempt' / '__retry_failed'）给 UI。
 *  - HTTP 4xx / 业务错误 / 用户 abort → 不重试，直接 yield。
 *
 * 元事件 schema：
 *   { event: '__retry_attempt', dataObj: { attempt, maxAttempts, delayMs, reason } }
 *   { event: '__retry_failed',  dataObj: { finalError, attempts } }
 *
 * 旧 3 参签名兼容：新参数 opts 可选（undefined 时开启默认重试）。
 */
export async function* runAgentStream(
  text: string,
  sessionId: string,
  signal: AbortSignal,
  opts?: RetryOptions & { retry?: boolean },
): AsyncGenerator<SseEvent> {
  const retryEnabled = opts?.retry !== false; // 默认 true
  const retryOpts: RetryOptions = {
    ...DEFAULT_RETRY_OPTIONS,
    ...(opts || {}),
    enabled: retryEnabled,
  };

  const controller = createAgentStreamController();
  // 把外部 signal 与 controller.signal 合并：任一 abort 都视为 abort
  const onExternalAbort = () => controller.abort();
  if (signal.aborted) controller.abort();
  else signal.addEventListener('abort', onExternalAbort, { once: true });

  // ============================================================
  // P1-2：重试主循环
  // ============================================================
  let attempt = 0;
  let lastErrorEv: { error: string; retryable: boolean; phase?: string } | null = null;

  while (true) {
    if (signal.aborted || controller.signal.aborted) {
      signal.removeEventListener('abort', onExternalAbort);
      return;
    }

    // —— 单次尝试 ——
    let res: Response;
    try {
      res = await fetch('/api/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
          provider: 'openai',
          model: 'gpt-4o-mini',
        }),
        signal: controller.signal,
      });
    } catch (e) {
      // fetch 自身失败（网络断开 / DNS / abort）→ 视为可重试
      if (e instanceof Error && e.name === 'AbortError') {
        signal.removeEventListener('abort', onExternalAbort);
        return;
      }
      const msg = e instanceof Error ? e.message : String(e);
      lastErrorEv = { error: msg, retryable: true, phase: 'fetch_throw' };
      yield {
        event: 'error',
        data: sharedFriendlyError(msg),
        dataObj: { type: 'error', error: msg, retryable: true, phase: 'fetch_throw' },
      };
      // 进入重试判定
      const decision = decideRetry(lastErrorEv, attempt, retryOpts);
      if (!retryEnabled || !decision.retry) {
        yield {
          event: '__retry_failed',
          data: '',
          dataObj: { finalError: msg, attempts: attempt + 1, reason: decision.reason },
        };
        signal.removeEventListener('abort', onExternalAbort);
        return;
      }
      // yield 元事件 + sleep
      yield {
        event: '__retry_attempt',
        data: '',
        dataObj: {
          attempt: attempt + 1,
          maxAttempts: retryOpts.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries,
          delayMs: decision.delayMs,
          reason: decision.reason,
        },
      };
      try {
        await sleep(decision.delayMs, signal);
      } catch {
        signal.removeEventListener('abort', onExternalAbort);
        return;
      }
      attempt += 1;
      retryOpts.onRetry?.({
        attempt: attempt,
        maxAttempts: retryOpts.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries,
        delayMs: decision.delayMs,
        reason: decision.reason,
      });
      continue;
    }

    if (!res.ok) {
      let body = '';
      try {
        body = await res.text();
      } catch {
        /* ignore */
      }
      const httpErrMsg = `HTTP ${res.status}: ${body || res.statusText}`;
      // 5xx → 可重试；4xx → 不可重试
      const retryable = res.status >= 500 || res.status === 429;
      lastErrorEv = { error: httpErrMsg, retryable, phase: 'http_status' };
      yield {
        event: 'error',
        data: sharedFriendlyError(httpErrMsg),
        dataObj: { type: 'error', error: httpErrMsg, retryable, phase: 'http_status', status: res.status },
      };
      const decision = decideRetry(lastErrorEv, attempt, retryOpts);
      if (!retryEnabled || !decision.retry) {
        yield {
          event: '__retry_failed',
          data: '',
          dataObj: { finalError: httpErrMsg, attempts: attempt + 1, reason: decision.reason, status: res.status },
        };
        signal.removeEventListener('abort', onExternalAbort);
        return;
      }
      yield {
        event: '__retry_attempt',
        data: '',
        dataObj: {
          attempt: attempt + 1,
          maxAttempts: retryOpts.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries,
          delayMs: decision.delayMs,
          reason: decision.reason,
        },
      };
      try {
        await sleep(decision.delayMs, signal);
      } catch {
        signal.removeEventListener('abort', onExternalAbort);
        return;
      }
      attempt += 1;
      retryOpts.onRetry?.({
        attempt: attempt,
        maxAttempts: retryOpts.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries,
        delayMs: decision.delayMs,
        reason: decision.reason,
      });
      continue;
    }

    // —— 200 OK：进入 SSE 流消费 ——
    let sawTerminalError = false;
    const events = await consumeSseStream(res, controller);
    for await (const ev of events) {
      // 解析 SSE 事件里 dataObj.retryable
      const obj = (ev.dataObj ?? {}) as {
        type?: string;
        retryable?: boolean;
        error?: string;
        phase?: string;
      };
      if (ev.event === 'error' || obj.type === 'error') {
        lastErrorEv = {
          error: obj.error ?? ev.data ?? 'unknown',
          retryable: obj.retryable === true,
          phase: obj.phase,
        };
        sawTerminalError = true;
        yield ev;
        break; // 跳出循环进入重试判定
      }
      yield ev;
    }

    if (!sawTerminalError) {
      // 正常结束（含 approval_required / approval_timeout 等不视为错误）
      signal.removeEventListener('abort', onExternalAbort);
      return;
    }

    // 进入重试判定
    const decision = decideRetry(lastErrorEv, attempt, retryOpts);
    if (!retryEnabled || !decision.retry) {
      yield {
        event: '__retry_failed',
        data: '',
        dataObj: {
          finalError: lastErrorEv?.error ?? 'unknown',
          attempts: attempt + 1,
          reason: decision.reason,
        },
      };
      signal.removeEventListener('abort', onExternalAbort);
      return;
    }
    yield {
      event: '__retry_attempt',
      data: '',
      dataObj: {
        attempt: attempt + 1,
        maxAttempts: retryOpts.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries,
        delayMs: decision.delayMs,
        reason: decision.reason,
      },
    };
    try {
      await sleep(decision.delayMs, signal);
    } catch {
      signal.removeEventListener('abort', onExternalAbort);
      return;
    }
    attempt += 1;
    retryOpts.onRetry?.({
      attempt: attempt,
      maxAttempts: retryOpts.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries,
      delayMs: decision.delayMs,
      reason: decision.reason,
    });
  }
}
