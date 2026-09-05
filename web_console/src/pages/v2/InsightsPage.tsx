/**
 * v2.0 slim — InsightsPage
 *
 * 聚合：Token 用量 / 错误率 / Trace 列表三个 widget。
 * 通过 query `?tab=xxx` 切换。
 *
 * 老 URL `/observability` 由 App.tsx 的 CompatRedirects 转发过来（→ ?tab=traces）。
 */
import { useSearchParams } from 'react-router-dom';
import { TokenUsageWidget } from '@/components/v2/TokenUsageWidget';
import { ErrorRateWidget } from '@/components/v2/ErrorRateWidget';
import { TraceListTable } from '@/components/v2/TraceListTable';

const TABS = ['usage', 'errors', 'traces'] as const;
type Tab = (typeof TABS)[number];

function isTab(s: string | null): s is Tab {
  return !!s && (TABS as readonly string[]).includes(s);
}

export function InsightsPage() {
  const [params, setParams] = useSearchParams();
  const tabParam = params.get('tab');
  const tab: Tab = isTab(tabParam) ? tabParam : 'usage';

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
      <div className="flex-1 overflow-y-auto p-6">
        {tab === 'usage' && <TokenUsageWidget />}
        {tab === 'errors' && <ErrorRateWidget />}
        {tab === 'traces' && <TraceListTable />}
      </div>
    </div>
  );
}

function labelOf(t: Tab): string {
  switch (t) {
    case 'usage':
      return 'Token 用量';
    case 'errors':
      return '错误率';
    case 'traces':
      return 'Trace';
  }
}