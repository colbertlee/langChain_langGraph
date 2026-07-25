import { useMemo, useCallback, useRef } from 'react';
import {
  useExternalStoreRuntime,
  type ExternalStoreThreadListAdapter,
  type ThreadMessage,
  type AppendMessage,
} from '@assistant-ui/react';
import { useChatStore } from '@/stores/chatStore';
import { attachmentAdapter } from '@/lib/attachmentAdapter';
import { uid } from '@/lib/utils';
import type { ChatMessage, ToolCall } from '@/types/api';

// ---- ChatMessage → assistant-ui ThreadMessage ----
type ToolCallPart = {
  type: 'tool-call';
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
  argsText: string;
  result?: string;
};
type TextPart = { type: 'text'; text: string };
type AnyPart = TextPart | ToolCallPart;

function toThreadMessage(m: ChatMessage): ThreadMessage {
  if (m.role === 'user') {
    return {
      id: m.id,
      role: 'user',
      content: [{ type: 'text', text: m.content }],
      createdAt: new Date(m.createdAt),
    } as unknown as ThreadMessage;
  }
  if (m.role === 'assistant') {
    const content: AnyPart[] = [];
    if (m.content) content.push({ type: 'text', text: m.content });
    for (const tc of m.toolCalls ?? []) {
      content.push({
        type: 'tool-call',
        toolCallId: tc.id,
        toolName: tc.name,
        args: tc.args,
        argsText: JSON.stringify(tc.args),
        result: tc.result,
      });
    }
    return {
      id: m.id,
      role: 'assistant',
      content,
      createdAt: new Date(m.createdAt),
    } as unknown as ThreadMessage;
  }
  return {
    id: m.id,
    role: m.role,
    content: [{ type: 'text', text: m.content }],
    createdAt: new Date(m.createdAt),
  } as unknown as ThreadMessage;
}

export function useAgentThreadListRuntime() {
  const messages = useChatStore((s) => s.messages[s.activeSessionId] ?? []);
  const append = useChatStore((s) => s.appendMessage);
  const update = useChatStore((s) => s.updateMessage);
  const streaming = useChatStore((s) => s.streaming);
  const setStreaming = useChatStore((s) => s.setStreaming);

  const threadMessages = useMemo(
    () => messages.map(toThreadMessage),
    [messages],
  );

  // 接收 assistant-ui 的 setMessages（对 store 浅同步）
  const setMessages = useCallback((next: readonly ThreadMessage[]) => {
    const sessionId = useChatStore.getState().activeSessionId;
    const mapped: ChatMessage[] = next.map((m) => {
      const id = (m as { id?: string }).id ?? uid();
      const role = (m as { role: 'user' | 'assistant' | 'system' | 'tool' }).role;
      const parts = ((m as { content: readonly AnyPart[] }).content ?? []) as readonly AnyPart[];
      const text = parts
        .filter((c): c is TextPart => c.type === 'text')
        .map((c) => c.text)
        .join('');
      const toolCalls: ToolCall[] = parts
        .filter((c): c is ToolCallPart => c.type === 'tool-call')
        .map<ToolCall>((c) => ({
          id: c.toolCallId,
          name: c.toolName,
          args: c.args,
          result: c.result,
          status: 'success',
          startedAt: Date.now(),
          endedAt: Date.now(),
        }));
      const created = (m as { createdAt?: Date | number }).createdAt;
      const createdAt =
        created instanceof Date
          ? created.getTime()
          : typeof created === 'number'
            ? created
            : Date.now();
      return { id, sessionId, role, content: text, toolCalls, createdAt };
    });
    useChatStore.setState((st) => ({
      messages: { ...st.messages, [sessionId]: mapped },
    }));
  }, []);

  // ---- 内部 SSE 驱动 ----
  const abortRef = useRef<AbortController | null>(null);

  const runAdapter = useCallback(
    async (text: string) => {
      const sessionId = useChatStore.getState().activeSessionId;
      const userMsg: ChatMessage = {
        id: uid(),
        sessionId,
        role: 'user',
        content: text,
        createdAt: Date.now(),
      };
      append(sessionId, userMsg);
      const assistantId = uid();
      append(sessionId, {
        id: assistantId,
        sessionId,
        role: 'assistant',
        content: '',
        toolCalls: [],
        createdAt: Date.now(),
      });
      setStreaming(true);
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        for await (const part of runStream(text, sessionId, controller.signal)) {
          applyPart(assistantId, sessionId, part);
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        update(sessionId, assistantId, {
          content: `> ⚠️ 请求失败：${msg}`,
        });
      } finally {
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [append, update, setStreaming],
  );

  const onNew = useCallback(
    async (msg: AppendMessage) => {
      const text = extractText(msg.content);
      if (text) await runAdapter(text);
    },
    [runAdapter],
  );

  const onEdit = useCallback(
    async (msg: AppendMessage) => {
      const text = extractText(msg.content);
      if (text) await runAdapter(text);
    },
    [runAdapter],
  );

  const onReload = useCallback(async () => {
    const lastUser = [...messages].reverse().find((m) => m.role === 'user');
    if (lastUser?.content) await runAdapter(lastUser.content);
  }, [messages, runAdapter]);

  const onCancel = useCallback(async () => {
    abortRef.current?.abort();
    setStreaming(false);
  }, [setStreaming]);

  // ---- thread list adapter ----
  const threadListAdapter: ExternalStoreThreadListAdapter = useMemo(() => {
    const build = (): ExternalStoreThreadListAdapter => {
      const s = useChatStore.getState();
      const threads = Object.values(s.sessions)
        .sort((a, b) => b.updatedAt - a.updatedAt)
        .map((x) => ({
          id: x.id,
          remoteId: x.id,
          title: x.title,
          status: 'regular' as const,
        }));
      return {
        threadId: s.activeSessionId,
        threads,
        archivedThreads: [],
        onSwitchToThread: (threadId: string) => {
          useChatStore.getState().setActive(threadId);
        },
        onSwitchToNewThread: () => {
          useChatStore.getState().newSession();
        },
        onRename: (threadId: string, title: string) => {
          useChatStore.getState().renameSession(threadId, title);
        },
        onDelete: (threadId: string) => {
          const cur = useChatStore.getState().activeSessionId;
          if (cur === threadId) useChatStore.getState().newSession();
          useChatStore.getState().deleteSession(threadId);
        },
        onArchive: (threadId: string) => {
          useChatStore.getState().deleteSession(threadId);
        },
      };
    };
    return build();
  }, [streaming]); // streaming 变化时重算（确保 actions 拿的是最新）

  return useExternalStoreRuntime({
    messages: threadMessages,
    setMessages,
    onNew,
    onEdit,
    onReload,
    onCancel,
    isRunning: streaming,
    adapters: {
      threadList: threadListAdapter,
      attachments: attachmentAdapter,
    },
  });
}

function extractText(content: unknown): string {
  if (!Array.isArray(content)) return '';
  return (content as unknown[])
    .filter(
      (c): c is TextPart =>
        !!c && typeof c === 'object' && (c as { type?: string }).type === 'text',
    )
    .map((c) => (c as TextPart).text ?? '')
    .join('')
    .trim();
}

type Part =
  | { type: 'text'; text: string }
  | {
      type: 'tool-call';
      toolCallId: string;
      toolName: string;
      args: Record<string, unknown>;
      result?: string;
    };

async function* runStream(
  text: string,
  sessionId: string,
  signal: AbortSignal,
): AsyncGenerator<Part> {
  const res = await fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, session_id: sessionId }),
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
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const raw of parts) {
      const line = raw.trim();
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload || payload === '[DONE]') continue;
      let ev: {
        type: string;
        content?: string;
        tool_call_id?: string;
        name?: string;
        args?: Record<string, unknown>;
        result?: string;
        error?: string;
      };
      try {
        ev = JSON.parse(payload);
      } catch {
        continue;
      }
      if (ev.type === 'token' && ev.content) {
        yield { type: 'text', text: ev.content };
      } else if (ev.type === 'tool_call' && ev.name) {
        yield {
          type: 'tool-call',
          toolCallId: ev.tool_call_id ?? uid(),
          toolName: ev.name,
          args: ev.args ?? {},
        };
      } else if (ev.type === 'tool_result' && ev.tool_call_id) {
        yield {
          type: 'tool-call',
          toolCallId: ev.tool_call_id,
          toolName: '',
          args: {},
          result: ev.result ?? '',
        };
      } else if (ev.type === 'error' && ev.error) {
        yield { type: 'text', text: `\n\n> ⚠️ ${ev.error}` };
      }
    }
  }
}

function applyPart(assistantId: string, sessionId: string, part: Part) {
  const update = useChatStore.getState().updateMessage;
  const cur = useChatStore.getState().messages[sessionId] ?? [];
  const a = cur.find((m) => m.id === assistantId);
  if (!a) return;
  if (part.type === 'text') {
    update(sessionId, assistantId, { content: (a.content ?? '') + part.text });
  } else if (part.type === 'tool-call') {
    if (part.toolName) {
      const tc: ToolCall = {
        id: part.toolCallId,
        name: part.toolName,
        args: part.args,
        status: 'running',
        startedAt: Date.now(),
      };
      update(sessionId, assistantId, {
        toolCalls: [...(a.toolCalls ?? []), tc],
      });
    } else if (part.result !== undefined) {
      const tcs = (a.toolCalls ?? []).map((t) =>
        t.id === part.toolCallId
          ? { ...t, result: part.result, status: 'success' as const, endedAt: Date.now() }
          : t,
      );
      update(sessionId, assistantId, { toolCalls: tcs });
    }
  }
}
