/**
 * WorkflowModeSelector — Chat 页面左上角「应用模式 / 工作流 (Workflow Mode)」下拉
 *
 * 替代旧版 SessionSidebar 顶部的「当前 AGENT」下拉。
 * 三个固定选项：
 *   - 通用对话 (Single Agent)
 *   - 复杂研发与重构 (Multi-Agent Swarm: Supervisor/Coder/Reviewer)
 *   - 深度数据分析 (Data Analyst)
 *
 * 选中后：
 *   - 写入 workflowStore.mode
 *   - 清空 workflowStore.logs（新模式新会话）
 *   - Chat 右侧实时执行日志面板 + Agents 监控页自动同步高亮对应节点
 */

import { useMemo, useState, type FC } from 'react';
import {
  ChevronDown,
  Workflow as WorkflowIcon,
  Sparkles,
  Network,
  BarChart3,
  Check,
} from 'lucide-react';
import { useWorkflowStore, WORKFLOW_MODES, WORKFLOW_MODE_ORDER } from '@/stores/workflowStore';
import type { WorkflowModeId } from '@/stores/workflowStore';
import { cn } from '@/lib/utils';

const MODE_ICONS: Record<WorkflowModeId, typeof WorkflowIcon> = {
  single: Sparkles,
  multi_swarm: Network,
  data_analyst: BarChart3,
};

export const WorkflowModeSelector: FC = () => {
  const mode = useWorkflowStore((s) => s.mode);
  const setMode = useWorkflowStore((s) => s.setMode);
  const [open, setOpen] = useState(false);

  const current = useMemo(() => WORKFLOW_MODES[mode], [mode]);

  const choose = (id: WorkflowModeId) => {
    if (id !== mode) setMode(id);
    setOpen(false);
  };

  const Icon = MODE_ICONS[mode];

  return (
    <div
      data-testid="workflow-mode-selector"
      data-mode={mode}
      className="relative"
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <WorkflowIcon className="w-3 h-3 text-accent1" />
        <span className="text-[10.5px] uppercase tracking-wider text-fg2 font-medium">
          应用模式 / 工作流 (Workflow Mode)
        </span>
      </div>
      <button
        type="button"
        data-testid="workflow-mode-trigger"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className={cn(
          'w-full h-8 pl-2 pr-1.5 bg-[var(--bg-0)] border rounded text-[12px] text-fg0',
          'flex items-center gap-2 outline-none transition-colors',
          open
            ? 'border-cyan-500/50'
            : 'border-[var(--border)] hover:border-cyan-500/30',
        )}
      >
        <span
          className={cn(
            'w-5 h-5 rounded-md flex items-center justify-center shrink-0',
            mode === 'multi_swarm'
              ? 'bg-accent-grad shadow-glow'
              : mode === 'data_analyst'
                ? 'bg-violet-500/20 text-violet-300'
                : 'bg-cyan-500/20 text-cyan-300',
          )}
        >
          <Icon className="w-3 h-3" />
        </span>
        <span className="flex-1 min-w-0 truncate text-left font-medium">
          {current.label}
        </span>
        <ChevronDown
          className={cn(
            'w-3.5 h-3.5 text-fg2 shrink-0 transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {current && (
        <div className="mt-1 text-[10px] text-fg2 truncate" title={current.description}>
          {current.description}
        </div>
      )}

      {open && (
        <div
          role="listbox"
          data-testid="workflow-mode-listbox"
          className="absolute left-0 right-0 top-full mt-1 z-50 bg-[var(--bg-1)] border border-[var(--border)] rounded-md shadow-2xl overflow-hidden"
        >
          {WORKFLOW_MODE_ORDER.map((id) => {
            const meta = WORKFLOW_MODES[id];
            const ItemIcon = MODE_ICONS[id];
            const isCurrent = id === mode;
            return (
              <button
                key={id}
                type="button"
                role="option"
                aria-selected={isCurrent}
                data-testid={`workflow-mode-option-${id}`}
                onClick={() => choose(id)}
                className={cn(
                  'w-full text-left px-2.5 py-2 flex items-start gap-2 hover:bg-[var(--bg-2)] transition-colors',
                  isCurrent && 'bg-cyan-500/10',
                )}
              >
                <span
                  className={cn(
                    'mt-0.5 w-6 h-6 rounded-md flex items-center justify-center shrink-0',
                    id === 'multi_swarm'
                      ? 'bg-accent-grad text-white shadow-glow'
                      : id === 'data_analyst'
                        ? 'bg-violet-500/20 text-violet-300'
                        : 'bg-cyan-500/20 text-cyan-300',
                  )}
                >
                  <ItemIcon className="w-3.5 h-3.5" />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-medium text-fg0 leading-tight">
                    {meta.label}
                  </div>
                  <div className="text-[10px] text-fg2 mt-0.5 leading-snug">
                    {meta.description}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-0.5">
                    {meta.nodes.map((n) => (
                      <span
                        key={n}
                        className="px-1 py-px rounded bg-[var(--bg-2)] text-fg1 font-mono text-[9.5px]"
                      >
                        {n}
                      </span>
                    ))}
                  </div>
                </div>
                {isCurrent && (
                  <Check className="w-3.5 h-3.5 text-cyan-300 mt-1 shrink-0" />
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
};