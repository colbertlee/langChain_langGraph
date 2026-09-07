/**
 * v2.0 slim — AdminPage
 *
 * 6 页面 → 1 Tab 页：Agents / Tools / Settings / Approval / Prompts / Memory。
 *
 * 旧页面组件（@/pages/Agents.tsx 等）原样保留，本页通过 React.lazy 复用，
 * 不重复实现。Tab key 同步写入 ?tab=xxx，便于分享链接。
 */
import { Suspense, lazy } from 'react';
import { useSearchParams } from 'react-router-dom';

const AgentsTab = lazy(() => import('@/pages/Agents').then((m) => ({ default: m.Agents })));
const ToolsTab = lazy(() => import('@/pages/Tools').then((m) => ({ default: m.Tools })));
const SettingsTab = lazy(() => import('@/pages/Settings').then((m) => ({ default: m.Settings })));
const ApprovalTab = lazy(() => import('@/pages/Approval').then((m) => ({ default: m.Approval })));
const PromptsTab = lazy(() => import('@/pages/Prompts').then((m) => ({ default: m.Prompts })));
const MemoryTab = lazy(() => import('@/pages/Memory').then((m) => ({ default: m.Memory })));

const TABS = [
  { key: 'agents', label: 'Agents', Comp: AgentsTab },
  { key: 'tools', label: 'Tools', Comp: ToolsTab },
  { key: 'settings', label: 'Settings', Comp: SettingsTab },
  { key: 'approval', label: 'Approval', Comp: ApprovalTab },
  { key: 'prompts', label: 'Prompts', Comp: PromptsTab },
  { key: 'memory', label: 'Memory', Comp: MemoryTab },
] as const;

type TabKey = (typeof TABS)[number]['key'];

export function AdminPage() {
  const [search, setSearch] = useSearchParams();
  const current = (search.get('tab') as TabKey) ?? 'agents';
  const active = TABS.find((t) => t.key === current) ?? TABS[0];

  const setTab = (key: TabKey) => {
    const next = new URLSearchParams(search);
    next.set('tab', key);
    setSearch(next, { replace: true });
  };

  return (
    <div className="p-4">
      <div role="tablist" className="flex gap-2 border-b border-[var(--border)] mb-4">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={t.key === active.key}
            onClick={() => setTab(t.key)}
            className={
              'px-3 py-2 text-sm border-b-2 -mb-px transition-colors ' +
              (t.key === active.key
                ? 'border-[var(--accent-2)] text-[var(--accent-2)]'
                : 'border-transparent text-[var(--fg-1)] hover:text-[var(--fg-0)]')
            }
          >
            {t.label}
          </button>
        ))}
      </div>
      <Suspense fallback={<div className="text-sm text-[var(--fg-2)]">Loading…</div>}>
        <active.Comp />
      </Suspense>
    </div>
  );
}
