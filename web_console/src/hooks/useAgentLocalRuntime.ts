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
  /** P0-1：工具返回结果（tool_result 事件携带） */
  result?: string;
  /** P0-1：工具耗时（tool_result / tool_end 携带，单位 ms） */
  duration_ms?: number;
  /** P0-1：工具终止状态（tool_end 携带："success" | "error" | "aborted"） */
  status?: string;
  error?: string;
};

/**
 * P1-1：thinking 增量缓冲。
 * 后端按 chunk 推 thinking 数据；前端用这个 buffer 累积并以
 * `ReasoningMessagePart`（assistant-ui 原生 part 类型）实时推流。
 * 流结束时用 EMPTY 字符串 + 同一个 partId 重发一次，确保 final 完整快照。
 */
const thinkingBuffer = { text: '', partId: '' };

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

    try {
      for await (const ev of runAgentStream(text, sessionId, abortSignal)) {
        const dataStr = typeof ev.data === 'string' ? ev.data : undefined;
        const isText = ev.type === 'token' || ev.type === 'text';

        // ----------------------------------------------------------
        // P1-1：thinking 折叠渲染 —— 升级为 assistant-ui 原生 ReasoningMessagePart
        //   - 后端 yield 多次 {"type":"thinking","data":"..."}（增量）
        //   - 前端把增量拼到 thinkingBuffer.text
        //   - 每收到一个 thinking 增量，立即 yield 一个 ReasoningMessagePart
        //     （type="reasoning", text=当前完整文本），让 ThinkingBlock 实时打字机跟随
        //   - partId 稳定：保证 runtime 把多次 yield 合并为同一 part
        //   - 流结束再 yield 一次空字符串作为完成信号（ThinkingBlock 据此把 isStreaming=false）
        // ----------------------------------------------------------
        if (ev.type === 'thinking') {
          const inc = (ev.data ?? ev.content ?? '').toString();
          if (!inc) continue;
          thinkingBuffer.text += inc;
          yield {
            content: [
              {
                type: 'reasoning',
                text: thinkingBuffer.text,
                partId: thinkingBuffer.partId,
              },
            ],
          } as unknown as ChatModelRunResult;
          continue;
        }

        // 流式 token / 普通文本
        if (isText && ev.content) {
          yield { content: [{ type: 'text', text: ev.content }] } as ChatModelRunResult;
        } else if (isText && dataStr) {
          yield { content: [{ type: 'text', text: dataStr }] } as ChatModelRunResult;

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
          const tcArgs = ev.args ?? {};
          toolCallsById.set(tcId, {
            name: tcName,
            args: tcArgs,
          });
          yield {
            content: [
              {
                type: 'tool-call',
                toolCallId: tcId,
                toolName: tcName,
                args: tcArgs,
                argsText: JSON.stringify(tcArgs),
              },
            ],
          } as unknown as ChatModelRunResult;

        // ----------------------------------------------------------
        // P0-2：tool_result —— 把 result 注入到对应 tool-call part
        //   - assistant-ui 不支持按 id 修改既有 part，所以 yield 一个新的
        //     tool-call part（带 result），runtime 会按 toolCallId 合并到原卡片。
        // ----------------------------------------------------------
        } else if (ev.type === 'tool_result' && ev.tool_call_id) {
          const tcId = ev.tool_call_id;
          const prev = toolCallsById.get(tcId) ?? {
            name: ev.name ?? 'tool',
            args: {},
          };
          toolCallsById.set(tcId, {
            ...prev,
            name: ev.name ?? prev.name,
            result: ev.result ?? dataStr ?? '',
            durationMs: ev.duration_ms ?? prev.durationMs,
          });
          yield {
            content: [
              {
                type: 'tool-call',
                toolCallId: tcId,
                toolName: prev.name,
                args: prev.args,
                argsText: JSON.stringify(prev.args),
                result: ev.result ?? dataStr ?? '',
              },
            ],
          } as unknown as ChatModelRunResult;

        // ----------------------------------------------------------
        // P0-2：tool_end —— 在消息流里 yield 一条简短文本（"✅ toolname 完成 (xx ms)"），
        // 同时把状态写回 store；不重复 yield tool-call part（tool_result 已足够）。
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
          yield {
            content: [
              {
                type: 'text',
                text: `\n\n> ✅ \`${name}\` 完成${durLabel}\n`,
              },
            ],
          } as ChatModelRunResult;

        } else if (ev.type === 'error') {
          // 兜底显示错误文本，确保用户能看到 agent 失败原因
          yield {
            content: [
              { type: 'text', text: `\n\n> ⚠️ ${dataStr ?? ev.error ?? 'unknown error'}` },
            ],
          } as ChatModelRunResult;
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
            // 同时在消息流里 yield 提示文本，让用户看到
            yield {
              content: [
                {
                  type: 'text',
                  text: `\n\n> ⚠️ **高风险工具需要确认**：\`${tName}\`\n> ${reason || '请在右侧审批面板中允许或拒绝。'}\n`,
                },
              ],
            } as ChatModelRunResult;
          } catch {
            /* HITL 登记失败不影响流 */
          }
        } else if (ev.type === 'approval_timeout') {
          // v2.2.1 — 超时自动拒绝：把对应卡片标记为 rejected (timed_out=true)，
          // 并 yield 提示文本告诉用户"系统自动取消了"
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
            yield {
              content: [
                {
                  type: 'text',
                  text: `\n\n> ⏰ **审批超时已自动取消**：${reason}\n`,
                },
              ],
            } as ChatModelRunResult;
          } catch {
            /* 忽略超时处理失败 */
          }
        } else if (ev.type === 'agent_switch') {
          // v2.2.3 — Multi-Agent Supervisor 切换 Worker：
          //   1) 写入 chatStore.agentEvents（用于 AgentExecutionGraph UI）
          //   2) yield 一段紧凑的 markdown，让用户在消息流里也看到切换日志
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
              yield {
                content: [
                  {
                    type: 'text',
                    text: `\n\n> 🔀 **Agent 切换** → \`${agentName}\`${reason ? `\n> ${reason}` : ''}\n`,
                  },
                ],
              } as ChatModelRunResult;
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
          yield {
            content: [
              {
                type: 'text',
                text: `\n\n> 🔁 **网络不稳定，正在自动重试**（第 ${attempt} 次 / 等待 ${secs}s）${reason ? `\n> 原因：${reason}` : ''}\n`,
              },
            ],
          } as ChatModelRunResult;
        } else if (ev.type === '__retry_failed') {
          // P1-2 — 重试次数耗尽，最终失败
          const attempts = (ev as { attempts?: number }).attempts ?? 0;
          const finalErr = (ev as { finalError?: string }).finalError ?? 'unknown';
          yield {
            content: [
              {
                type: 'text',
                text: `\n\n> ❌ **已重试 ${attempts} 次仍失败**：${finalErr}\n> 请稍后再试，或检查网络 / API Key 配置。\n`,
              },
            ],
          } as ChatModelRunResult;
        }
      }

      // ----------------------------------------------------------
      // P1-1：流结束 → ThinkingBlock 收到 isStreaming=false，自动收起
      // 这里不再额外 yield text part。thinking 内容已通过 ReasoningMessagePart
      // 实时推流并合并到 partId；runtime 会自然把状态切到 complete。
      // ----------------------------------------------------------
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
