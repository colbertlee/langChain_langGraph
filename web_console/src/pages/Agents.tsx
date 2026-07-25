import { useEffect, useState } from 'react';
import { Bot, Cpu, MemoryStick, Activity, Loader2, AlertCircle, PlayCircle } from 'lucide-react';
import { api } from '@/lib/api';
import type { Agent } from '@/types/api';
import { cn } from '@/lib/utils';

export function Agents() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Agent | null>(null);

  useEffect(() => {
    let cancel = false;
    const load = async () => {
      try {
        const list = await api.agents();
        if (!cancel) setAgents(list);
      } catch {
        // 后端未启动时使用演示数据
        if (!cancel) {
          setAgents(MOCK_AGENTS);
        }
      } finally {
        if (!cancel) setLoading(false);
      }
    };
    load();
    const t = window.setInterval(load, 10000);
    return () => {
      cancel = true;
      window.clearInterval(t);
    };
  }, []);

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-accent1 animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-7xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 stagger">
          {agents.map((a) => (
            <AgentCard key={a.id} agent={a} onClick={() => setSelected(a)} />
          ))}
        </div>
      </div>
      {selected && <AgentDetail agent={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function AgentCard({ agent, onClick }: { agent: Agent; onClick: () => void }) {
  const statusColor =
    agent.status === 'running'
      ? 'text-accent1'
      : agent.status === 'error'
        ? 'text-danger'
        : 'text-fg2';
  const dot =
    agent.status === 'running'
      ? 'bg-accent1 animate-pulse-soft'
      : agent.status === 'error'
        ? 'bg-danger'
        : 'bg-fg2';
  const load = Math.min(100, Math.max(0, agent.load));
  return (
    <button
      onClick={onClick}
      className="grad-border p-5 text-left hover:translate-y-[-2px] transition-transform"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-[10px] flex items-center justify-center bg-[var(--bg-2)] border border-[var(--border)]">
            <Bot className={cn('w-5 h-5', statusColor)} strokeWidth={1.6} />
          </div>
          <div>
            <div className="text-[14px] font-semibold text-fg0">{agent.name}</div>
            <div className="text-[10.5px] text-fg2 font-mono">{agent.id}</div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 text-[11px]">
          <span className={cn('dot', dot)} />
          <span className={statusColor}>{agent.status}</span>
        </div>
      </div>
      <div className="mb-3">
        <div className="text-[11px] text-fg2 mb-1.5 flex items-center gap-1">
          <Activity className="w-3 h-3" /> Load
        </div>
        <div className="h-1.5 rounded-full bg-[var(--bg-2)] overflow-hidden">
          <div
            className="h-full rounded-full bg-accent-grad transition-all"
            style={{ width: `${load}%` }}
          />
        </div>
        <div className="text-[10.5px] text-fg2 font-mono mt-1">{load}%</div>
      </div>
      <div className="flex flex-wrap gap-1">
        {agent.capabilities.slice(0, 4).map((c) => (
          <span key={c} className="badge">
            {c}
          </span>
        ))}
        {agent.capabilities.length > 4 && (
          <span className="badge">+{agent.capabilities.length - 4}</span>
        )}
      </div>
      {agent.currentTask && (
        <div className="mt-3 pt-3 border-t border-[var(--border)] text-[11.5px] text-fg1 flex items-center gap-1.5">
          <PlayCircle className="w-3 h-3 text-accent1 shrink-0" />
          <span className="truncate">{agent.currentTask}</span>
        </div>
      )}
    </button>
  );
}

function AgentDetail({ agent, onClose }: { agent: Agent; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6 animate-fade-in-up"
      onClick={onClose}
    >
      <div
        className="glass-strong rounded-[16px] p-6 w-full max-w-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-[10px] flex items-center justify-center bg-accent-grad">
              <Bot className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="text-lg font-semibold">{agent.name}</div>
              <div className="text-xs text-fg2 font-mono">{agent.id}</div>
            </div>
          </div>
          <button onClick={onClose} className="btn-ghost h-8">
            关闭
          </button>
        </div>
        <div className="grid grid-cols-3 gap-3 mb-5">
          <Stat icon={Activity} label="Status" value={agent.status} />
          <Stat icon={Cpu} label="Load" value={`${agent.load}%`} />
          <Stat icon={MemoryStick} label="Capabilities" value={String(agent.capabilities.length)} />
        </div>
        <div className="text-xs uppercase tracking-wider text-fg2 mb-2 font-mono">Capabilities</div>
        <div className="flex flex-wrap gap-1.5 mb-4">
          {agent.capabilities.map((c) => (
            <span key={c} className="badge badge-accent">
              {c}
            </span>
          ))}
          {agent.capabilities.length === 0 && (
            <div className="text-fg2 text-sm flex items-center gap-1.5">
              <AlertCircle className="w-3.5 h-3.5" /> 暂无能力注册
            </div>
          )}
        </div>
        {agent.profile && (
          <>
            <div className="text-xs uppercase tracking-wider text-fg2 mb-2 font-mono">Profile</div>
            <pre className="font-mono text-[11.5px] text-fg1 bg-[rgba(0,0,0,0.4)] rounded-md p-3 overflow-x-auto max-h-64">
              {JSON.stringify(agent.profile, null, 2)}
            </pre>
          </>
        )}
      </div>
    </div>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
}) {
  return (
    <div className="card p-3">
      <div className="flex items-center gap-1.5 text-[10.5px] text-fg2 uppercase tracking-wider mb-1">
        <Icon className="w-3 h-3" />
        {label}
      </div>
      <div className="text-[16px] font-bold text-fg0 font-mono">{value}</div>
    </div>
  );
}

const MOCK_AGENTS: Agent[] = [
  {
    id: 'supervisor-01',
    name: 'Supervisor',
    status: 'running',
    capabilities: ['task_routing', 'plan_synthesis', 'negotiation'],
    load: 62,
    currentTask: '路由用户查询 → coder-02',
    profile: { model: 'gpt-4o', uptime_s: 3842 },
  },
  {
    id: 'coder-02',
    name: 'Coder',
    status: 'idle',
    capabilities: ['python_exec', 'code_review', 'file_io'],
    load: 12,
    profile: { model: 'claude-3.5-sonnet' },
  },
  {
    id: 'researcher-01',
    name: 'Researcher',
    status: 'running',
    capabilities: ['web_search', 'rag', 'summarize'],
    load: 78,
    currentTask: 'RAG: knowledge_base/python_intro.txt',
  },
  {
    id: 'analyst-01',
    name: 'Analyst',
    status: 'error',
    capabilities: ['etf', 'chart', 'numeric'],
    load: 0,
    profile: { error: 'tool timeout' },
  },
  {
    id: 'reviewer-01',
    name: 'Reviewer',
    status: 'idle',
    capabilities: ['code_review', 'security', 'permission'],
    load: 8,
  },
  {
    id: 'github-bot',
    name: 'GitHub Operator',
    status: 'idle',
    capabilities: ['github_search', 'github_issue', 'github_pr'],
    load: 0,
  },
];
