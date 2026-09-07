/**
 * v2.1 — useAgentLocalRuntime
 *
 * 把 chat 状态彻底本地化（runtime 内部 state），不再依赖 zustand 镜像。
 * 与后端 SSE 流打通：用户发消息 → runtime 自动调用 chatModel.run →
 * 本 hook 把 SSE 事件解析后以 AsyncGenerator 增量 yield 给 runtime。
 *
 * 历史数据从 zustand chatStore 一次性 hydrate 成 initialMessages。
 */
import { useMemo } from 'react';
import {
  useLocalRuntime,
  type ChatModelAdapter,
  type ChatModelRunOptions,
  type ChatModelRunResult,
} from '@assistant-ui/react';
import { useChatStore } from '@/stores/chatStore';
import { attachmentAdapter } from '@/lib/attachmentAdapter';
import { chatHistoryAdapter } from '@/lib/chatHistoryAdapter';
import { uid } from '@/lib/utils';

type AgentTextPart = { type: 'text'; text: string };

function extractText(content: unknown): string {
  if (!Array.isArray(content)) return '';
  return (content as unknown[])
    .filter(
      (c): c is AgentTextPart =>
        !!c && typeof c === 'object' && (c as { type?: string }).type === 'text',
    )
    .map((c) => (c as AgentTextPart).text ?? '')
    .join('')
    .trim();
}

// 后端 SSE run_stream 协议事件类型。data 字段携带字符串内容（token 文本 / 错误消息）。
type StreamEvent = {
  type: string;
  data?: string;
  content?: string;
  name?: string;
  args?: Record<string, unknown>;
  tool_call_id?: string;
  result?: string;
  error?: string;
};

async function* runAgentStream(
  text: string,
  sessionId: string,
  signal: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      message: text,
      session_id: sessionId,
      provider: 'openai',
      model: 'gpt-4o-mini',
    }),
    signal,
  });
  if (!res.body) return;
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 事件以 \n\n 分隔；每个事件由多行组成（event: ...\ndata: ...）。
    const events = buffer.split('\n\n');
    buffer = events.pop() ?? '';
    for (const evBlock of events) {
      const dataLines: string[] = [];
      for (const ln of evBlock.split('\n')) {
        const trimmed = ln.trim();
        if (trimmed.startsWith('data:')) {
          const payload = trimmed.slice(5).trim();
          if (payload && payload !== '[DONE]') dataLines.push(payload);
        }
      }
      if (dataLines.length === 0) continue;
      try {
        // 后端 run_stream 单事件一个 JSON 串
        const parsed = JSON.parse(dataLines.join('\n')) as StreamEvent;
        yield parsed;
      } catch {
        /* skip malformed */
      }
    }
  }
}

function streamToChatModelResult(opts: ChatModelRunOptions) {
  const { messages, abortSignal } = opts;
  const lastUser = [...messages].reverse().find((m) => m.role === 'user');
  const text = lastUser ? extractText(lastUser.content) : '';
  const sessionId = useChatStore.getState().activeSessionId;

  async function* gen() {
    if (!text) {
      yield { content: [] };
      return;
    }
    try {
      for await (const ev of runAgentStream(text, sessionId, abortSignal)) {
        const dataStr = typeof ev.data === 'string' ? ev.data : undefined;
        const isText = ev.type === 'token' || ev.type === 'text';
        if (isText && ev.content) {
          yield { content: [{ type: 'text', text: ev.content }] } as ChatModelRunResult;
        } else if (isText && dataStr) {
          yield { content: [{ type: 'text', text: dataStr }] } as ChatModelRunResult;
        } else if (ev.type === 'tool_call' && (ev.name || dataStr)) {
          yield {
            content: [
              {
                type: 'tool-call',
                toolCallId: ev.tool_call_id ?? uid(),
                toolName: ev.name ?? dataStr ?? 'tool',
                args: ev.args ?? {},
                argsText: JSON.stringify(ev.args ?? {}),
              },
            ],
          } as unknown as ChatModelRunResult;
        } else if (ev.type === 'tool_result' && ev.tool_call_id) {
          yield {
            content: [
              {
                type: 'tool-call',
                toolCallId: ev.tool_call_id,
                toolName: '',
                args: {},
                result: ev.result ?? dataStr ?? '',
              },
            ],
          } as unknown as ChatModelRunResult;
        } else if (ev.type === 'error') {
          // 兜底显示错误文本，确保用户能看到 agent 失败原因
          yield {
            content: [
              { type: 'text', text: `\n\n> ⚠️ ${dataStr ?? ev.error ?? 'unknown error'}` },
            ],
          } as ChatModelRunResult;
        }
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (e instanceof Error && e.name === 'AbortError') {
        // 用户取消：安静退出
        return;
      }
      yield { content: [{ type: 'text', text: `> ⚠️ 请求失败：${msg}` }] } as ChatModelRunResult;
    }
  }

  return gen();
}

export function useAgentLocalRuntime() {
  // 注意：本 hook 不订阅 activeSessionId —— history adapter 内部用 useChatStore.getState()
  // 读最新值，避免 zustand 通知触发 hook re-run 与 LocalRuntime 生命周期冲突。
  //
  // 会话切换策略：调用方 ChatPage 用 key={activeSessionId} 包裹 AssistantRuntimeProvider，
  // 这样切会话时 React 会 unmount/remount 整个 Provider 子树，LocalRuntime 重建并重新
  // 调用 history.load() 拿新 session 的消息。

  // chatModel：AsyncGenerator 流式输出（每次 yield 一帧 content，runtime 自动合并到 assistant 消息）
  const chatModel = useMemo<ChatModelAdapter>(
    () => ({
      run: (options: ChatModelRunOptions) => streamToChatModelResult(options),
    }),
    [],
  );

  return useLocalRuntime(chatModel, {
    adapters: {
      attachments: attachmentAdapter,
      history: chatHistoryAdapter,
    },
  });
}
