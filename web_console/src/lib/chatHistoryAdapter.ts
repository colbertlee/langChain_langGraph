/**
 * v2.1 — chatHistoryAdapter
 *
 * 把 assistant-ui useLocalRuntime 的 messages 持久化到 zustand chatStore，
 * 配合现有的 localStorage persist 实现"刷新页面后消息还在"。
 *
 * 设计要点：
 * 1. load() 从 chatStore 当前 session 取已有 messages 转成 ExportedMessageRepository；
 * 2. append() 把新消息（含 user、assistant、tool）写到 chatStore；
 * 3. update() 改写同 id 消息（用于 assistant 流式累积 / 状态更新 / 删除分支）；
 * 4. delete() 物理删除消息（按当前 activeSessionId 隔离）；
 *
 * 注意：assistant-ui ThreadMessage 结构比我们的 ChatMessage 复杂（含 status、metadata、
 * content parts 等），我们把 content parts 平展为 text + toolCalls 写到 ChatMessage。
 */
import type { ThreadHistoryAdapter } from '@assistant-ui/react';
import { useChatStore } from '@/stores/chatStore';
import type { ChatMessage, ToolCall } from '@/types/api';

type AppendItem = Parameters<ThreadHistoryAdapter['append']>[0];

// ExportedMessage 在新版 @assistant-ui 中未直接 re-export。这里给一个
// 本地最小等价类型（保留 m.message 的 id/role/createdAt/content 形状）。
type ExportedMessage = {
  message: {
    id?: string;
    role?: 'user' | 'assistant' | 'system' | 'tool';
    createdAt?: Date | string | number;
    content?: unknown;
  };
};

function flattenContent(content: unknown): {
  text: string;
  toolCalls: ToolCall[];
} {
  const parts = Array.isArray(content) ? (content as unknown[]) : [];
  let text = '';
  const toolCalls: ToolCall[] = [];
  for (const p of parts) {
    if (!p || typeof p !== 'object') continue;
    const part = p as { type?: string; text?: string };
    if (part.type === 'text' && typeof part.text === 'string') {
      text += part.text;
    } else if (part.type === 'tool-call') {
      const tc = p as {
        toolCallId?: string;
        toolName?: string;
        args?: Record<string, unknown>;
        argsText?: string;
        result?: unknown;
      };
      toolCalls.push({
        id: tc.toolCallId ?? '',
        name: tc.toolName ?? '',
        // ToolCall.args 在 ChatMessage 中是 Record<string, unknown> | undefined；
        // tc.args 已经是 Record<string, unknown> | undefined，直接透传即可。
        args: tc.args ?? {},
        result:
          typeof tc.result === 'string'
            ? tc.result
            : tc.result
              ? JSON.stringify(tc.result)
              : undefined,
        status: 'success',
        startedAt: Date.now(),
        endedAt: Date.now(),
      });
    }
  }
  return { text, toolCalls };
}

function messageToChatMessage(m: ExportedMessage['message']): ChatMessage {
  const role = (m as { role?: string }).role ?? 'user';
  const id = (m as { id?: string }).id;
  const created = (m as { createdAt?: Date | string | number }).createdAt;
  const createdAt =
    created instanceof Date
      ? created.getTime()
      : typeof created === 'string' || typeof created === 'number'
        ? new Date(created).getTime()
        : Date.now();
  const { text, toolCalls } = flattenContent(
    (m as { content?: unknown }).content,
  );
  return {
    id: id ?? `msg_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    sessionId: '', // 由调用方填
    role: role as ChatMessage['role'],
    content: text,
    toolCalls,
    createdAt,
  };
}

function getSessionId(): string {
  return useChatStore.getState().activeSessionId;
}

export const chatHistoryAdapter: ThreadHistoryAdapter = {
  async load() {
    const state = useChatStore.getState();
    const sid = state.activeSessionId;
    const list = state.messages[sid] ?? [];
    if (list.length === 0) {
      return { messages: [] };
    }
    try {
      // 动态 import @assistant-ui/core/internal（vitest-only export），
      // 用其内部的 ExportedMessageRepository.fromBranchableArray 把 ThreadMessageLike 转成完整 ThreadMessage，
      // 自动补齐 status/metadata/toolCallId 等字段，避免下游访问 undefined。
      const mod = await import('@assistant-ui/core/internal');
      const ExportedMessageRepository = mod.ExportedMessageRepository;
      // ExportedMessageRepository.fromBranchableArray 的 role 不接受 'tool'；
      // 把 tool 角色的消息折叠进上一条 assistant 的 tool-call parts（history view 不需要 tool role）。
      // 简单起见：tool 角色也映射为 'assistant'，工具调用 part 保留。
      return ExportedMessageRepository.fromBranchableArray(
        list.map((m, idx) => ({
          parentId: idx > 0 ? list[idx - 1].id : null,
          message: {
            id: m.id,
            role: (m.role === 'tool' ? 'assistant' : m.role) as
              | 'user'
              | 'assistant'
              | 'system',
            content: [
              ...(m.content ? [{ type: 'text' as const, text: m.content }] : []),
              ...(m.toolCalls ?? []).map((tc) => ({
                type: 'tool-call' as const,
                toolCallId: tc.id,
                toolName: tc.name,
                args: tc.args ?? {},
                argsText: JSON.stringify(tc.args ?? {}),
                result: tc.result,
              })),
            ] as unknown as import('@assistant-ui/react').ThreadMessageLike['content'],
            createdAt: new Date(m.createdAt),
          },
        })),
        { headId: list[list.length - 1]?.id ?? null },
      );
    } catch {
      // 加载失败时回退到空仓库（页面会显示 EmptyState），避免整页崩溃
      return { messages: [] };
    }
  },

  async append(item) {
    const sid = getSessionId();
    const cm = messageToChatMessage(item.message);
    cm.sessionId = sid;
    useChatStore.getState().appendMessage(sid, cm);
  },

  async update(item) {
    const sid = getSessionId();
    const cm = messageToChatMessage(item.message);
    cm.sessionId = sid;
    useChatStore.getState().updateMessage(sid, cm.id, {
      content: cm.content,
      toolCalls: cm.toolCalls,
    });
  },

  async delete(items) {
    const sid = getSessionId();
    const removeMessage = useChatStore.getState().removeMessage;
    if (!removeMessage) return;
    for (const it of items) {
      const id = (it.message as { id?: string })?.id;
      if (id) removeMessage(sid, id);
    }
  },
};
