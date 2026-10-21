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
import { runAgentStream } from '@/lib/runAgentStream';
import type { SseEvent } from '@/lib/sseParser';
import { uid } from '@/lib/utils';

type AgentTextPart = { type: 'text'; text: string };
type AgentReasoningPart = { type: 'reasoning'; text: string };
type AgentToolCallPart = {
  type: 'tool-call';
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
  argsText: string;
  result?: string;
};
/** 本轮消息的 part 累积容器：assistant-ui 每次 yield 都要全量快照。 */
type AgentPart = AgentTextPart | AgentReasoningPart | AgentToolCallPart;

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
  /** P0-1：工具返回结果（tool_result 事件携带） */
  result?: string;
  /** P0-1：工具耗时（tool_result / tool_end 携带，单位 ms） */
  duration_ms?: number;
  /** P0-1：工具终止状态（tool_end 携带："success" | "error" | "aborted"） */
  status?: string;
  error?: string;
  /** P1-2：自动重试元事件字段（__retry_attempt / __retry_failed） */
  attempt?: number;
  attempts?: number;
  delayMs?: number;
  reason?: string;
  finalError?: string;
  /** v2.2.1：HITL 审批事件字段 */
  request_id?: string;
  tool_args?: Record<string, unknown>;
  /** v2.2.3：Multi-Agent 事件字段 */
  agent?: string;
};

/** 文本增量事件别名：chunk / token 统一按 text 分支处理。 */
const TEXT_EVENT_TYPES = new Set(['chunk', 'token', 'text']);

/**
 * SseEvent（lib/sseParser）→ StreamEvent（本文件协议形态）适配。
 * 只做字段搬运，不改变下方 switch 分支语义：
 *  - 类型以 payload.type 为准，缺失时退回 SSE `event:` 头；
 *  - chunk / token 归一为 text；
 *  - payload.data 优先；SSE data 为非 JSON 纯文本时直接作为内容；
 *  - 其余字段从 payload 展开（含 HITL / Multi-Agent / retry 元事件）。
 */
function toStreamEvent(sse: SseEvent): StreamEvent {
  const obj = (
    sse.dataObj && typeof sse.dataObj === 'object' ? sse.dataObj : {}
  ) as Record<string, unknown>;
  const rawType = typeof obj.type === 'string' ? obj.type : sse.event;
  const data =
    typeof obj.data === 'string'
      ? obj.data
      : sse.dataObj === null && sse.data !== '[DONE]'
        ? sse.data
        : undefined;
  const rawArgs = obj.args ?? obj.tool_args;
  return {
    type: TEXT_EVENT_TYPES.has(rawType) ? 'text' : rawType,
    data,
    content: typeof obj.content === 'string' ? obj.content : undefined,
    name:
      (obj.name as string | undefined) ?? (obj.tool_name as string | undefined),
    args:
      rawArgs && typeof rawArgs === 'object'
        ? (rawArgs as Record<string, unknown>)
        : undefined,
    tool_call_id: obj.tool_call_id as string | undefined,
    result: obj.result as string | undefined,
    duration_ms: obj.duration_ms as number | undefined,
    status: obj.status as string | undefined,
    error: obj.error as string | undefined,
    attempt: obj.attempt as number | undefined,
    attempts: obj.attempts as number | undefined,
    delayMs: obj.delayMs as number | undefined,
    reason: obj.reason as string | undefined,
    finalError: obj.finalError as string | undefined,
    request_id: obj.request_id as string | undefined,
    tool_args: obj.tool_args as Record<string, unknown> | undefined,
    agent: obj.agent as string | undefined,
  };
}


/**
 * P1-1：thinking 增量缓冲。
 * 后端按 chunk 推 thinking 数据；前端用这个 buffer 累积并以
 * `ReasoningMessagePart`（assistant-ui 原生 part 类型）实时推流。
 * 流结束时用 EMPTY 字符串 + 同一个 partId 重发一次，确保 final 完整快照。
 */
const thinkingBuffer = { text: '', partId: '' };

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
    // P1-1：每次新 run 都重置 thinking buffer + 本轮工具调用表
    thinkingBuffer.text = '';
    thinkingBuffer.partId = uid();
    /** tool_call_id → {name, args, result?, status?, durationMs?} —— 用于汇总工具最终态 */
    const toolCallsById = new Map<
      string,
      {
        name: string;
        args: Record<string, unknown>;
        result?: string;
        status?: string;
        durationMs?: number;
      }
    >();

    // ----------------------------------------------------------
    // assistant-ui 的 LocalRuntime 把每次 yield 视为「整条消息的完整快照」：
    // local-thread-runtime-core 的 updateMessage 是 initialContent + 本次 content，
    // 不会把连续多次 yield 的 content 拼起来。所以这里必须自行累积 parts，
    // 每个事件都 yield 全量快照，否则后一个事件会把前一个 part 覆盖掉。
    // ----------------------------------------------------------
    const parts: AgentPart[] = [];
    const snapshot = (): ChatModelRunResult =>
      ({ content: parts.map((p) => ({ ...p })) }) as unknown as ChatModelRunResult;

    let activeText: AgentTextPart | null = null;
    /** 追加文本；当前段不是 text part 时新开一段 */
    const appendText = (t: string): void => {
      if (activeText === null) {
        const part: AgentTextPart = { type: 'text', text: t };
        parts.push(part);
        activeText = part;
        return;
      }
      activeText.text += t;
    };
    /** 断开当前文本段，后续文本另起一段（避免拼进工具/思考块前后） */
    const breakText = (): void => {
      activeText = null;
    };

    let reasoningPart: AgentReasoningPart | null = null;
    const toolPartById = new Map<string, AgentToolCallPart>();

    try {
      for await (const sse of runAgentStream(text, sessionId, abortSignal)) {
        const ev = toStreamEvent(sse);
        const dataStr = typeof ev.data === 'string' ? ev.data : undefined;
        const isText = ev.type === 'token' || ev.type === 'text';

        // ----------------------------------------------------------
        // P1-1：thinking 折叠渲染 —— assistant-ui 原生 ReasoningMessagePart
        //   - 后端 yield 多次 {"type":"thinking","data":"..."}（增量）
        //   - 前端把增量拼到 thinkingBuffer.text，同一个 part 原地更新
        //   - 每次 yield 全量快照，ThinkingBlock 实时打字机跟随
        // ----------------------------------------------------------
        if (ev.type === 'thinking') {
          const inc = (ev.data ?? ev.content ?? '').toString();
          if (!inc) continue;
          thinkingBuffer.text += inc;
          if (reasoningPart === null) {
            reasoningPart = { type: 'reasoning', text: thinkingBuffer.text };
            parts.push(reasoningPart);
          } else {
            reasoningPart.text = thinkingBuffer.text;
          }
          breakText();
          yield snapshot();
          continue;
        }

        // 流式 token / 普通文本：累加到当前 text part
        if (isText && (ev.content || dataStr)) {
          appendText(ev.content ?? dataStr ?? '');
          yield snapshot();

        // ----------------------------------------------------------
        // P0-2：tool_start —— 创建 tool-call part（带 args，result 留空 → 显示菊花）
        //   - 与 tool_call（兼容事件）合并到同一条分支，避免重复创建 part
        // ----------------------------------------------------------
        } else if (
          (ev.type === 'tool_start' || ev.type === 'tool_call') &&
          (ev.name || dataStr)
        ) {
          const tcId = ev.tool_call_id ?? uid();
          const tcName = ev.name ?? dataStr ?? 'tool';
          // tool_call（兼容事件）可能不带 args：沿用同 id 已登记的 args，
          // 避免把 tool_start 的完整参数覆盖成 {}。
          const tcArgs = ev.args ?? toolCallsById.get(tcId)?.args ?? {};
          toolCallsById.set(tcId, {
            name: tcName,
            args: tcArgs,
          });
          const existing = toolPartById.get(tcId);
          if (existing) {
            existing.toolName = tcName;
            existing.args = tcArgs;
            existing.argsText = JSON.stringify(tcArgs);
          } else {
            const part: AgentToolCallPart = {
              type: 'tool-call',
              toolCallId: tcId,
              toolName: tcName,
              args: tcArgs,
              argsText: JSON.stringify(tcArgs),
            };
            parts.push(part);
            toolPartById.set(tcId, part);
          }
          breakText();
          yield snapshot();

        // ----------------------------------------------------------
        // P0-2：tool_result —— 把 result 注入到对应 tool-call part（原地更新）
        // ----------------------------------------------------------
        } else if (ev.type === 'tool_result' && ev.tool_call_id) {
          const tcId = ev.tool_call_id;
          const prev = toolCallsById.get(tcId) ?? {
            name: ev.name ?? 'tool',
            args: {},
          };
          const result = ev.result ?? dataStr ?? '';
          toolCallsById.set(tcId, {
            ...prev,
            name: ev.name ?? prev.name,
            result,
            durationMs: ev.duration_ms ?? prev.durationMs,
          });
          const existing = toolPartById.get(tcId);
          if (existing) {
            existing.result = result;
          } else {
            const part: AgentToolCallPart = {
              type: 'tool-call',
              toolCallId: tcId,
              toolName: prev.name,
              args: prev.args,
              argsText: JSON.stringify(prev.args),
              result,
            };
            parts.push(part);
            toolPartById.set(tcId, part);
          }
          breakText();
          yield snapshot();

        // ----------------------------------------------------------
        // P0-2：tool_end —— 在消息流里追加一条简短文本（"✅ toolname 完成 (xx ms)"），
        // 同时把状态写回内存表；不重复创建 tool-call part（tool_result 已足够）。
        // ----------------------------------------------------------
        } else if (ev.type === 'tool_end' && ev.tool_call_id) {
          const tcId = ev.tool_call_id;
          const prev = toolCallsById.get(tcId);
          if (prev) {
            toolCallsById.set(tcId, {
              ...prev,
              status: ev.status ?? 'success',
              durationMs: ev.duration_ms ?? prev.durationMs,
            });
          }
          const name = ev.name ?? prev?.name ?? 'tool';
          const ms = ev.duration_ms ?? prev?.durationMs;
          const durLabel = typeof ms === 'number' ? ` (${Math.round(ms)} ms)` : '';
          appendText(`\n\n> ✅ \`${name}\` 完成${durLabel}\n`);
          breakText();
          yield snapshot();

        } else if (ev.type === 'error') {
          // 兜底显示错误文本，确保用户能看到 agent 失败原因
          appendText(`\n\n> ⚠️ ${dataStr ?? ev.error ?? 'unknown error'}`);
          breakText();
          yield snapshot();
        } else if (ev.type === 'approval_required') {
          // v2.2.1 — HITL 拦截：把审批事件登记到 chatStore，并在流里插入提示文本
          // 后端会暂停状态图，等待用户在前端点击「允许」/「拒绝」
          try {
            const reqId = (ev as { request_id?: string; tool_call_id?: string })
              .request_id;
            const tName = ev.name ?? dataStr ?? 'unknown_tool';
            const tArgs = (ev as { tool_args?: Record<string, unknown> }).tool_args ?? {};
            const reason = (ev as { reason?: string }).reason ?? '';
            if (reqId) {
              useChatStore.getState().recordApproval({
                id: reqId,
                sessionId,
                toolName: tName,
                toolArgs: tArgs,
                reason,
              });
            }
            // 同时在消息流里追加提示文本，让用户看到
            appendText(
              `\n\n> ⚠️ **高风险工具需要确认**：\`${tName}\`\n> ${reason || '请在右侧审批面板中允许或拒绝。'}\n`,
            );
            breakText();
            yield snapshot();
          } catch {
            /* HITL 登记失败不影响流 */
          }
        } else if (ev.type === 'approval_timeout') {
          // v2.2.1 — 超时自动拒绝：把对应卡片标记为 rejected (timed_out=true)，
          // 并追加提示文本告诉用户"系统自动取消了"
          try {
            const reqId = (ev as { request_id?: string }).request_id;
            const reason = (ev as { reason?: string }).reason ?? 'Approval request timed out';
            if (reqId) {
              useChatStore.getState().resolveApproval(
                sessionId,
                reqId,
                'rejected',
                reason,
              );
            }
            appendText(`\n\n> ⏰ **审批超时已自动取消**：${reason}\n`);
            breakText();
            yield snapshot();
          } catch {
            /* 忽略超时处理失败 */
          }
        } else if (ev.type === 'agent_switch') {
          // v2.2.3 — Multi-Agent Supervisor 切换 Worker：
          //   1) 写入 chatStore.agentEvents（用于 AgentExecutionGraph UI）
          //   2) 追加一段紧凑的 markdown，让用户在消息流里也看到切换日志
          try {
            const agentName = (ev as { agent?: string }).agent ?? dataStr ?? '';
            const reason = (ev as { reason?: string }).reason ?? '';
            const reqId = (ev as { request_id?: string }).request_id;
            if (agentName) {
              useChatStore.getState().appendAgentEvent(sessionId, {
                sessionId,
                type: 'switch',
                agent: agentName,
                reason: reason || undefined,
                ...(reqId ? { requestId: reqId } : {}),
              });
              appendText(
                `\n\n> 🔀 **Agent 切换** → \`${agentName}\`${reason ? `\n> ${reason}` : ''}\n`,
              );
              breakText();
              yield snapshot();
            }
          } catch {
            /* 静默忽略 agent_switch 处理失败（UI 仍可继续） */
          }
        } else if (ev.type === 'agent_done') {
          // v2.2.3 — 当前 Worker / 整轮结束
          try {
            const agentName = (ev as { agent?: string }).agent ?? 'FINISH';
            useChatStore.getState().appendAgentEvent(sessionId, {
              sessionId,
              type: 'done',
              agent: agentName,
            });
          } catch {
            /* ignore */
          }
        } else if (ev.type === '__retry_attempt') {
          // P1-2 — 自动重试中，向用户渲染一条短提示
          const attempt = (ev as { attempt?: number }).attempt ?? 1;
          const delayMs = (ev as { delayMs?: number }).delayMs ?? 0;
          const reason = (ev as { reason?: string }).reason ?? '';
          const secs = Math.max(1, Math.round(delayMs / 1000));
          appendText(
            `\n\n> 🔁 **网络不稳定，正在自动重试**（第 ${attempt} 次 / 等待 ${secs}s）${reason ? `\n> 原因：${reason}` : ''}\n`,
          );
          breakText();
          yield snapshot();
        } else if (ev.type === '__retry_failed') {
          // P1-2 — 重试次数耗尽，最终失败
          const attempts = (ev as { attempts?: number }).attempts ?? 0;
          const finalErr = (ev as { finalError?: string }).finalError ?? 'unknown';
          appendText(
            `\n\n> ❌ **已重试 ${attempts} 次仍失败**：${finalErr}\n> 请稍后再试，或检查网络 / API Key 配置。\n`,
          );
          breakText();
          yield snapshot();
        }
      }

      // ----------------------------------------------------------
      // P1-1：流结束 → ThinkingBlock 收到 isStreaming=false，自动收起
      // ----------------------------------------------------------
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (e instanceof Error && e.name === 'AbortError') {
        // 用户取消：安静退出
        return;
      }
      appendText(`> ⚠️ 请求失败：${msg}`);
      breakText();
      yield snapshot();
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

  // 同步稳定的 adapters 配置对象 —— 避免每次 render 生成新字面量导致
  // useLocalRuntime/useSyncExternalStore 检测到"store 实例变化"而触发 effect 重跑，
  // 进而陷入 `Maximum update depth exceeded` 死循环。
  const options = useMemo<Parameters<typeof useLocalRuntime>[1]>(
    () => ({
      adapters: {
        attachments: attachmentAdapter,
        history: chatHistoryAdapter,
      },
    }),
    [],
  );

  return useLocalRuntime(chatModel, options);
}
