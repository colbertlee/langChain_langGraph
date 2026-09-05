/**
 * v2.0 slim — ToolCallTimeline
 *
 * 极简版工具调用时间线：监听 chatStore 的 toolCalls 字段，按时间倒序展示。
 * 不引入第三方时间线库。
 */
import { useChatStore } from '@/stores/chatStore';

export function ToolCallTimeline() {
  const toolCalls = useChatStore((s) => s.toolCalls ?? []);
  if (!toolCalls.length) {
    return <p className="text-xs text-slate-500">暂无工具调用</p>;
  }
  return (
    <ul className="space-y-1 text-xs">
      {toolCalls.slice().reverse().map((tc, i) => (
        <li key={i} className="border-l-2 border-blue-400 pl-2">
          <div className="font-mono">{tc.tool}.{tc.subcommand ?? ''}</div>
          <div className="text-slate-500">{tc.status} · {tc.durationMs ?? 0}ms</div>
        </li>
      ))}
    </ul>
  );
}