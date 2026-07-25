import { useLocation } from 'react-router-dom';
import { Github, BookOpen } from 'lucide-react';

const TITLES: Record<string, { title: string; sub: string }> = {
  '/': { title: 'Chat', sub: '与 Agent 实时对话，流式输出 · 工具可视化' },
  '/agents': { title: 'Agents', sub: '多 Agent 集群状态 · 能力 · 负载' },
  '/approval': { title: 'Human-in-the-Loop', sub: '审批 Agent 的高风险操作' },
  '/observability': { title: 'Observability', sub: '事件流 · Trace · Prometheus 指标' },
  '/tools': { title: 'Tools', sub: 'Agent 可用工具与能力广场' },
  '/settings': { title: 'Settings', sub: 'Provider · Model · API Key' },
};

export function TopBar() {
  const { pathname } = useLocation();
  const t = TITLES[pathname] ?? TITLES['/'];

  return (
    <header className="h-14 flex items-center justify-between gap-4 px-6 border-b border-[var(--border)] glass-strong shrink-0">
      <div className="flex flex-col leading-tight min-w-0">
        <h1 className="text-[15px] font-semibold tracking-tight truncate">
          {t.title}
        </h1>
        <p className="text-[11.5px] text-fg2 truncate">{t.sub}</p>
      </div>
      <div className="flex items-center gap-2">
        <a
          href="https://github.com/colbertlee/langChain_langGraph"
          target="_blank"
          rel="noreferrer"
          className="btn-ghost h-8 px-2.5"
        >
          <Github className="w-4 h-4" />
          <span className="hidden sm:inline">Repo</span>
        </a>
        <a href="/docs" className="btn-ghost h-8 px-2.5">
          <BookOpen className="w-4 h-4" />
          <span className="hidden sm:inline">Docs</span>
        </a>
      </div>
    </header>
  );
}
