import { useLocation, useSearchParams } from 'react-router-dom';
import { Github, BookOpen, Sun, Moon } from 'lucide-react';
import { useUIStore } from '@/stores/uiStore';

const TITLES: Record<string, { title: string; sub: string }> = {
  '/': { title: 'Chat', sub: '与 Agent 实时对话，流式输出 · 工具可视化' },
  '/chat': { title: 'Chat', sub: '与 Agent 实时对话，流式输出 · 工具可视化' },
  '/admin': { title: 'Admin', sub: '多 Agent · 工具 · 设置 · 审批 · 提示 · 记忆' },
  '/insights': { title: 'Observability', sub: '事件流 · Trace · Prometheus 指标' },
};

const TAB_TITLES: Record<string, string> = {
  agents: 'Agents',
  tools: 'Tools',
  settings: 'Settings',
  approval: 'Human-in-the-Loop',
  prompts: 'Prompts',
  memory: 'Memory',
};

const TAB_SUBS: Record<string, string> = {
  agents: '多 Agent 集群状态 · 能力 · 负载',
  tools: 'Agent 可用工具与能力广场',
  settings: 'Provider · Model · API Key',
  approval: '审批 Agent 的高风险操作',
  prompts: 'Prompt 版本管理 · 导入导出',
  memory: 'Agent 长期记忆与上下文',
};

export function TopBar() {
  const { pathname } = useLocation();
  const [search] = useSearchParams();
  const base = TITLES[pathname] ?? TITLES['/'];
  // /admin?tab=xxx → 用 tab 名覆盖
  const tab = search.get('tab');
  const t = pathname === '/admin' && tab
    ? { title: TAB_TITLES[tab] ?? base.title, sub: TAB_SUBS[tab] ?? base.sub }
    : base;
  const theme = useUIStore((s) => s.theme);
  const toggleTheme = useUIStore((s) => s.toggleTheme);
  const isLight = theme === 'light';

  return (
    <header
      className="h-14 flex items-center justify-between gap-4 px-6 border-b border-[var(--border)] shrink-0 transition-colors"
      style={{ backgroundColor: 'var(--bg-1)' }}
    >
      <div className="flex flex-col leading-tight min-w-0">
        <h1 className="text-[15px] font-semibold tracking-tight truncate">
          {t.title}
        </h1>
        <p className="text-[11.5px] text-fg2 truncate">{t.sub}</p>
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={toggleTheme}
          className="btn-ghost h-8 px-2.5"
          aria-label={isLight ? '切换到深色主题' : '切换到浅色主题'}
          title={isLight ? '切换到深色主题' : '切换到浅色主题'}
        >
          {isLight ? (
            <Moon className="w-4 h-4" strokeWidth={2} />
          ) : (
            <Sun className="w-4 h-4" strokeWidth={2} />
          )}
          <span className="hidden sm:inline">{isLight ? '深色' : '浅色'}</span>
        </button>
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
