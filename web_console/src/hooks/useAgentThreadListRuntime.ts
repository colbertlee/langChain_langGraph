/**
 * v2.1 — useAgentThreadListRuntime (stub)
 *
 * 历史组件 Chat.tsx 引用此 hook。当前 v2 路由已改用 useAgentLocalRuntime
 * + AssistantRuntimeProvider，Chat.tsx 不再被路由表引用。本文件保留以满足
 * 历史 import 不报 TS2307。
 *
 * 行为：返回 null，由调用方自行降级。
 */
import type {
  AssistantRuntime,
  ChatModelAdapter,
  ChatModelRunOptions,
} from '@assistant-ui/react';

/**
 * 历史组件 Chat.tsx 引用此 hook。当前 v2 路由已改用 useAgentLocalRuntime
 * + AssistantRuntimeProvider，Chat.tsx 不再被路由表引用。本文件保留以满足
 * 历史 import 不报 TS2307。
 *
 * 返回 null：调用方需要做条件渲染。
 */
export function useAgentThreadListRuntime(): AssistantRuntime | null {
  return null;
}

// 重新导出助手-ui 类型，避免被 Tree-shaking 误删
export type { ChatModelAdapter, ChatModelRunOptions };
