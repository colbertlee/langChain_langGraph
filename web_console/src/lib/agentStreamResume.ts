/**
 * P1-5 — HITL 拒绝/批准后订阅 resume SSE 流（前端）
 *
 * 后端 chat_reject / chat_approve 返回 `{resume_url: "/api/chat/{rid}/resume"}`，
 * 前端用 fetch + ReadableStream 订阅该 URL，把续生成事件原样转发给 caller。
 *
 * 与 runAgentStream 的差异：
 *  - 不自动重试（resume 失败应让用户重新 reject/approve）
 *  - 不主动 abort controller.signal（让 caller 决定何时停止）
 *  - yield 的是 SseEvent（与 runAgentStream 同协议），caller 复用 streamToChatModelResult
 *
 * 用法：
 *   for await (const ev of resumeAgentStream(rid, sid, signal)) {
 *     ... // ev 是 SseEvent；交给 normalizeSseEvents / streamToChatModelResult
 *   }
 */
import {
  parseSseStream,
  isTerminalSseEvent,
  friendlyError as sharedFriendlyError,
  type SseEvent,
} from './sseParser';

export interface ResumeOptions {
  /** 基础 URL，默认走同源（同 vite proxy 转发） */
  baseUrl?: string;
}

/**
 * 订阅 HITL resume SSE 流，把续生成事件原样 yield 给 caller。
 * 流结束（end/done 帧 / 连接断开 / signal abort）后退出。
 */
export async function* resumeAgentStream(
  requestId: string,
  sessionId: string,
  signal: AbortSignal,
  opts: ResumeOptions = {},
): AsyncGenerator<SseEvent> {
  const base = opts.baseUrl ?? '';
  const url = `${base}/api/chat/${encodeURIComponent(requestId)}/resume?session_id=${encodeURIComponent(sessionId)}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'text/event-stream' },
      signal,
    });
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    const msg = e instanceof Error ? e.message : String(e);
    yield {
      event: 'error',
      data: sharedFriendlyError(msg),
      dataObj: { type: 'error', error: msg, retryable: false, phase: 'resume_fetch_throw' },
    };
    yield { event: 'end', data: '{}', dataObj: { type: 'end' } };
    return;
  }

  if (!res.ok) {
    let body = '';
    try {
      body = await res.text();
    } catch {
      /* ignore */
    }
    yield {
      event: 'error',
      data: sharedFriendlyError(`HTTP ${res.status}: ${body || res.statusText}`),
      dataObj: {
        type: 'error',
        error: `HTTP ${res.status}: ${body || res.statusText}`,
        retryable: false,
        phase: 'resume_http_status',
        status: res.status,
      },
    };
    yield { event: 'end', data: '{}', dataObj: { type: 'end' } };
    return;
  }

  if (!res.body) {
    yield {
      event: 'error',
      data: sharedFriendlyError('Empty response from server'),
      dataObj: { type: 'error', error: 'empty body', retryable: false, phase: 'resume_empty' },
    };
    yield { event: 'end', data: '{}', dataObj: { type: 'end' } };
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      if (signal.aborted) return;
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = parseSseStream(buffer);
      const lastSep = buffer.lastIndexOf('\n\n');
      if (lastSep >= 0) buffer = buffer.slice(lastSep + 2);

      for (const ev of events) {
        yield ev;
        if (isTerminalSseEvent(ev)) {
          try {
            await reader.cancel();
          } catch {
            /* ignore */
          }
          return;
        }
      }
    }
  } catch (e) {
    if (e instanceof Error && e.name === 'AbortError') return;
    const msg = e instanceof Error ? e.message : String(e);
    yield {
      event: 'error',
      data: sharedFriendlyError(msg),
      dataObj: { type: 'error', error: msg, retryable: false, phase: 'resume_stream_throw' },
    };
  } finally {
    try {
      await reader.cancel();
    } catch {
      /* ignore */
    }
  }

  // 兜底：流正常断开但没收到 end/done，补一个 end 帧
  yield { event: 'end', data: '{}', dataObj: { type: 'end' } };
}
