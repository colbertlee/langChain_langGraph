/**
 * v2.1 slim — ToolCallTimeline
 *
 * 监听 assistant-ui runtime 当前 thread 的 tool calls 展示时间线。
 * 不再依赖 chatStore（那里没有 toolCalls 字段）—— 直接通过 useAui() 拿。
 */
import { useMemo } from 'react';
import { useAuiState } from '@assistant-ui/react';

export function ToolCallTimeline() {
  const msgs = useAuiState((s) => s.thread.messages);
  const toolCalls = useMemo(() => {
    type Row = { id: string; tool: string; subcommand?: string; status: string; durationMs?: number };
    const rows: Row[] = [];
    for (const m of msgs) {
      if (m.role !== 'assistant') continue;
      for (const p of m.content ?? []) {
        // assistant-ui 工具调用 part 类型：'tool-call'
        if ((p as { type?: string }).type === 'tool-call') {
          const tc = p as {
            toolCallId?: string;
            toolName?: string;
            result?: unknown;
            args?: Record<string, unknown>;
          };
          rows.push({
            id: tc.toolCallId ?? Math.random().toString(36).slice(2),
            tool: tc.toolName ?? 'tool',
            subcommand: (tc.args?.subcommand as string | undefined) ?? (tc.args?.command as string | undefined),
            status: tc.result !== undefined ? 'success' : 'running',
          });
        }
      }
    }
    return rows.reverse();
  }, [msgs]);

  if (toolCalls.length === 0) {
    return <p className="text-xs text-slate-500">暂无工具调用</p>;
  }
  return (
    <ul className="space-y-1 text-xs">
      {toolCalls.map((tc) => (
        <li key={tc.id} className="border-l-2 border-blue-400 pl-2">
          <div className="font-mono">{tc.tool}{tc.subcommand ? `.${tc.subcommand}` : ''}</div>
          <div className="text-slate-500">{tc.status}</div>
        </li>
      ))}
    </ul>
  );
}
