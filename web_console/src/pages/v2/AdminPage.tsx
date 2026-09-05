/**
 * v2.0 slim — AdminPage（Tab 聚合）
 *
 * 把 v1 散落的 Agents / Tools / Settings / Approval / Memory / Prompts
 * 六个页面统一聚合到一个 AdminPage 下，通过 query `?tab=xxx` 切换。
 *
 * 使用 React.lazy 动态 import 旧页面，避免一次性加载所有 v1 代码。
 * 老 URL（/agents /tools /settings /approval /prompts /memory）由 App.tsx 的
 * CompatRedirects 转发过来。
 */
import { Suspense, lazy } from 'react';
import { useSearchParams } from 'react-router-dom';

const AgentsView = lazy(() => import('@/pages/Agents').then((m) => ({ default: m.Agents })));
const ToolsView = lazy(() => import('@/pages/Tools').then((m) => ({ default: m.Tools })));
const SettingsView = lazy(() => import('@/pages/Settings').then((m) => ({ default: m.Settings })));
const ApprovalView = lazy(() => import('@/pages/Approval').then((m) => ({ default: m.Approval })));
const MemoryView = lazy(() => import('@/pages/Memory').then((m) => ({ default: m.Memory })));
const PromptsView = lazy(() => import('@/pages/Prompts').then((m) => ({ default: m.Prompts })));

const TABS = ['agents', 'tools', 'settings', 'approval', 'memory', 'prompts'] as const;
type Tab = (typeof TABS)[number];

function isTab(s: string | null): s is Tab {
  return !!s && (TABS as readonly string[]).includes(s);
}

export function AdminPage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get('tab');
  const tab: Tab = isTab(tabParam) ? tabParam : 'agents';

  return (
    <div className="flex flex-col h-full">
      <nav className="flex gap-1 border-b border-slate-200 dark:border-slate-800 px-4 pt-3">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setParams({ tab: t })}
            className={
              'px-3 py-1.5 text-sm rounded-t-md ' +
              (tab === t
                ? 'bg-white dark:bg-slate-900 text-slate-900 dark:text-slate-100 font-semibold border border-slate-200 dark:border-slate-800 border-b-white dark:border-b-slate-900'
                : 'text-slate-500 hover:text-slate-700 dark:hover:text-slate-300')
            }
          >
            {labelOf(t)}
          </button>
        ))}
      </nav>
      <div className="flex-1 overflow-y-auto">
        <Suspense fallback={<div className="p-6 text-slate-400">加载中…</div>}>
          {tab === 'agents' && <AgentsView />}
          {tab === 'tools' && <ToolsView />}
          {tab === 'settings' && <SettingsView />}
          {tab === 'approval' && <ApprovalView />}
          {tab === 'memory' && <MemoryView />}
          {tab === 'prompts' && <PromptsView />}
        </Suspense>
      </div>
    </div>
  );
}

function labelOf(t: Tab): string {
  switch (t) {
    case 'agents':
      return 'Agents';
    case 'tools':
      return '工具';
    case 'settings':
      return '设置';
    case 'approval':
      return '审批';
    case 'memory':
      return '记忆';
    case 'prompts':
      return 'Prompts';
  }
}