/**
 * P1-2 — 流式错误自动重试（前端侧）
 *
 * 设计：
 *  - 后端 `event_gen` 在异常分支 / 流静默断开时 yield `{type:"error", retryable:bool, ...}`，
 *    供前端按 retryable 字段决定是否重试。
 *  - 前端 `runAgentStream` 在捕获到 retryable=true 的 error 时：
 *      1) yield 一个 `__retry_attempt` 元事件（让 UI 能渲染"重连中…"提示）
 *      2) sleep 指数退避（默认 1s → 2s → 4s）
 *      3) 重新发起一次 POST /api/chat/stream，复用同一个 session_id
 *      4) 最多 N 次（默认 2），全失败后 yield 最终 error 给 UI
 *  - 不可重试的错误（HTTP 4xx / 用户错误 / 业务异常）→ 直接 yield，不再重试。
 *
 * 抽出到独立文件：
 *  - 便于单元测试覆盖（不依赖 fetch / DOM）
 *  - useAgentLocalRuntime 只负责「拼接进 ChatModelRunResult」
 *  - runAgentStream 只负责「调 fetch + 解析 SSE」
 *
 * 与 P1-5 的衔接：
 *  - 重试只针对「网络/服务端瞬时故障」；
 *  - HITL reject 后的续生成走单独的 `/api/chat/{request_id}/resume` SSE 通道
 *    （见 P1-5 agentStreamResume.ts）。
 */

export interface RetryOptions {
  /** 最大重试次数（默认 2） */
  maxRetries?: number;
  /** 基础退避毫秒（默认 1000，第一次失败后等 1s 再重试） */
  baseBackoffMs?: number;
  /** 退避上限毫秒（默认 8000） */
  maxBackoffMs?: number;
  /** 是否启用（默认 true；测试可设 false 加速） */
  enabled?: boolean;
  /** 用户主动 abort 时是否中断重试（默认 true） */
  abortOnUserCancel?: boolean;
  /** 重试时回调（attempt 序号），UI 可显示 */
  onRetry?: (info: {
    attempt: number;
    maxAttempts: number;
    delayMs: number;
    reason: string;
  }) => void;
}

export const DEFAULT_RETRY_OPTIONS: Required<Omit<RetryOptions, 'onRetry' | 'abortOnUserCancel'>> = {
  maxRetries: 2,
  baseBackoffMs: 1000,
  maxBackoffMs: 8000,
  enabled: true,
};

export interface RetryDecision {
  /** 是否要重试 */
  retry: boolean;
  /** 距下次重试的延迟（毫秒） */
  delayMs: number;
  /** 重试原因（用于日志 / UI） */
  reason: string;
}

/**
 * 判定一次失败是否需要重试，并计算退避延迟。
 *
 * 规则：
 *  - retryable=true → 重试；
 *  - retryable=false 或缺失 → 不重试；
 *  - attempt 超过 maxRetries → 不重试。
 *  - 退避：baseBackoffMs * 2^attempt，clamp 到 maxBackoffMs。
 */
export function decideRetry(
  errorEv: { retryable?: boolean; error?: string } | null | undefined,
  attempt: number,
  opts: RetryOptions = {},
): RetryDecision {
  const max = opts.maxRetries ?? DEFAULT_RETRY_OPTIONS.maxRetries;
  if (attempt >= max) {
    return { retry: false, delayMs: 0, reason: 'max_retries_reached' };
  }
  if (errorEv && errorEv.retryable === true) {
    const base = opts.baseBackoffMs ?? DEFAULT_RETRY_OPTIONS.baseBackoffMs;
    const cap = opts.maxBackoffMs ?? DEFAULT_RETRY_OPTIONS.maxBackoffMs;
    const delay = Math.min(base * 2 ** attempt, cap);
    const reason = errorEv.error
      ? `retryable error: ${errorEv.error.slice(0, 120)}`
      : 'retryable error';
    return { retry: true, delayMs: delay, reason };
  }
  return { retry: false, delayMs: 0, reason: 'not_retryable' };
}

/**
 * 一个 sleep 工具（避免直接 await setTimeout，便于测试 mock）。
 */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('aborted', 'AbortError'));
      return;
    }
    const timer = setTimeout(resolve, ms);
    if (signal) {
      const onAbort = () => {
        clearTimeout(timer);
        reject(new DOMException('aborted', 'AbortError'));
      };
      signal.addEventListener('abort', onAbort, { once: true });
    }
  });
}

/**
 * 把一次失败汇总成归一化的「retry 决策 + 错误对象」。
 */
export function buildRetryableError(
  errorEv: { retryable?: boolean; error?: string } | null | undefined,
): { retryable: boolean; message: string } {
  return {
    retryable: errorEv?.retryable === true,
    message: errorEv?.error ?? 'unknown error',
  };
}
