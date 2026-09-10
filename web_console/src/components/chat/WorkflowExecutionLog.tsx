/**
 * WorkflowExecutionLog — Chat 右侧实时执行日志 / 节点状态面板
 *
 * 显示当前 workflow mode 的拓扑（节点 + Supervisor→Coder/Reviewer 的边），
 * 并把 runtime 推送过来的 WorkflowExecLog 实时展示在节点下方。
 *
 * 工作模式：
 *  - single：只显示 "General Agent" 单节点
 *  - multi_swarm：Supervisor / Coder / Reviewer 三节点 + 三条边
 *  - data_analyst：Analyst / Coder 双节点
 */

import { useEffect, useMemo, useRef } from 'react';
import {
  Activity,
  ArrowRight,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Loader2,
  Workflow as WorkflowIcon,
  XCircle,
  Wrench,
  Cpu,
  BarChart3,
  Network,
  Sparkles,
} from 'lucide-react';
import {
  useWorkflowStore,
  WORKFLOW_MODES,
  type WorkflowExecLog,
  type WorkflowModeId,
} from '@/stores/workflowStore';
import { cn } from '@/lib/utils';

const NODE_ICONS: Record<string, typeof Bot> = {
  'supervisor-01': Network,
  'coder-02': Cpu,
  'reviewer-01': CheckCircle2,
  'analyst-01': BarChart3,
  general: Sparkles,
};

const MODE_ACCENT: Record<WorkflowModeId, string> = {
  single: 'border-cyan-500/30 bg-cyan-500/5',
  multi_swarm: 'border-accent1/40 bg-accent-grad/5',
  data_analyst: 'border-violet-500/30 bg-violet-500/5',
};

function fmtTime(ts: number): string {
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  const ss = String(d.getSeconds()).padStart(2, '0');
  return `${hh}:${mm}:${ss}`;
}

function statusDot(s?: WorkflowExecLog['status']) {
  if (s === 'running') return <Loader2 className="w-3 h-3 animate-spin text-cyan-400" />;
  if (s === 'error') return <XCircle className="w-3 h-3 text-rose-400" />;
  if (s === 'success') return <CheckCircle2 className="w-3 h-3 text-emerald-400" />;
  return <CircleDashed className="w-3 h-3 text-fg2" />;
}

export function WorkflowExecutionLog() {
  const mode = useWorkflowStore((s) => s.mode);
  const logs = useWorkflowStore((s) => s.logs);
  const clearLogs = useWorkflowStore((s) => s.clearLogs);
  const meta = WORKFLOW_MODES[mode];

  // 自动滚动到最新的日志（视觉）
  const listRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [logs.length]);

  // 把日志按 nodeId 分桶，便于渲染到每个节点卡片下方
  const logsByNode = useMemo(() => {
    const map = new Map<string, WorkflowExecLog[]>();
    for (const n of meta.nodes) map.set(n, []);
    for (const l of logs) {
      const arr = map.get(l.nodeId);
      if (arr) arr.push(l);
      else map.set(l.nodeId, [l]);
    }
    return map;
  }, [logs, meta.nodes]);

  return (
    <div
      data-testid="workflow-execution-log"
      data-mode={mode}
      className={cn('rounded-[12px] border p-3', MODE_ACCENT[mode])}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-1.5">
          <WorkflowIcon className="w-3.5 h-3.5 text-accent1" />
          <h3 className="text-[12.5px] font-semibold text-fg0">
            工作流执行日志
          </h3>
          <span className="ml-1 text-[10px] text-fg2 font-mono">
            {logs.length} 条
          </span>
        </div>
        <button
          type="button"
          onClick={clearLogs}
          disabled={logs.length === 0}
          className="text-[10px] text-fg2 hover:text-fg0 disabled:opacity-40 disabled:cursor-not-allowed"
          title="清空日志"
        >
          清空
        </button>
      </div>

      {/* 拓扑节点 */}
      <div className="space-y-2 mb-2">
        {meta.nodes.map((nid, idx) => {
          const NodeIcon = NODE_ICONS[nid] ?? Bot;
          const nodeLogs = logsByNode.get(nid) ?? [];
          const last = nodeLogs[nodeLogs.length - 1];
          const isActive = last?.status === 'running';
          return (
            <div key={nid}>
              {idx > 0 && meta.edges.some((e) => e.to === nid) && (
                <div className="flex items-center gap-1 pl-2 py-0.5 text-fg2">
                  <ArrowRight className="w-3 h-3 rotate-90" />
                  <span className="text-[9.5px] font-mono opacity-70">dispatch</span>
                </div>
              )}
              <div
                data-testid={`workflow-node-${nid}`}
                className={cn(
                  'rounded-md border px-2 py-1.5 transition-colors',
                  isActive
                    ? 'border-cyan-500/40 bg-cyan-500/5'
                    : 'border-[var(--border)] bg-[var(--bg-1)]',
                )}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      'w-6 h-6 rounded-md flex items-center justify-center shrink-0',
                      isActive
                        ? 'bg-accent-grad text-white shadow-glow'
                        : 'bg-[var(--bg-2)] text-fg1',
                    )}
                  >
                    <NodeIcon className="w-3.5 h-3.5" />
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-[11.5px] font-medium text-fg0 font-mono truncate">
                        {nid}
                      </span>
                      {isActive && (
                        <span className="text-[9.5px] px-1 rounded bg-cyan-500/15 text-cyan-300">
                          running
                        </span>
                      )}
                    </div>
                    <div className="text-[10px] text-fg2 truncate">
                      {last?.message ?? (isActive ? '等待任务…' : 'idle')}
                    </div>
                  </div>
                  {statusDot(last?.status)}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* 全量日志（最新在下） */}
      <div className="border-t border-[var(--border)] pt-2">
        <div className="flex items-center gap-1 mb-1.5">
          <Activity className="w-3 h-3 text-fg2" />
          <span className="text-[10px] uppercase tracking-wider text-fg2 font-medium">
            事件流
          </span>
        </div>
        <div
          ref={listRef}
          className="max-h-[200px] overflow-y-auto space-y-0.5 pr-1"
          data-testid="workflow-execution-log-list"
        >
          {logs.length === 0 ? (
            <div className="text-[10.5px] text-fg2 py-3 text-center">
              暂无事件。开始对话后这里会显示 Supervisor 分发、Coder 执行、Reviewer 审查的实时步骤。
            </div>
          ) : (
            logs.slice(-100).map((l) => (
              <div
                key={l.id}
                className="flex items-start gap-1.5 text-[10.5px] font-mono leading-snug py-0.5"
                data-testid="workflow-execution-log-row"
                data-kind={l.kind}
              >
                <span className="text-fg2 shrink-0">{fmtTime(l.ts)}</span>
                <span className="shrink-0">
                  {l.kind === 'tool_call' || l.kind === 'tool_result' ? (
                    <Wrench className="w-2.5 h-2.5 text-fg1 inline" />
                  ) : l.kind === 'dispatch' ? (
                    <ChevronRight className="w-2.5 h-2.5 text-cyan-300 inline" />
                  ) : l.kind === 'error' ? (
                    <XCircle className="w-2.5 h-2.5 text-rose-400 inline" />
                  ) : l.kind === 'complete' ? (
                    <CheckCircle2 className="w-2.5 h-2.5 text-emerald-400 inline" />
                  ) : (
                    <CircleDashed className="w-2.5 h-2.5 text-fg2 inline" />
                  )}
                </span>
                <span
                  className={cn(
                    'shrink-0 px-1 rounded text-[9.5px]',
                    l.status === 'error'
                      ? 'bg-rose-500/15 text-rose-300'
                      : l.status === 'running'
                        ? 'bg-cyan-500/15 text-cyan-300'
                        : l.status === 'success'
                          ? 'bg-emerald-500/15 text-emerald-300'
                          : 'bg-[var(--bg-2)] text-fg1',
                  )}
                >
                  {l.nodeId}
                </span>
                {l.toNodeId && (
                  <>
                    <span className="text-fg2">→</span>
                    <span className="shrink-0 px-1 rounded bg-cyan-500/10 text-cyan-200 text-[9.5px]">
                      {l.toNodeId}
                    </span>
                  </>
                )}
                <span className="flex-1 min-w-0 text-fg1 truncate" title={l.message}>
                  {l.message}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}