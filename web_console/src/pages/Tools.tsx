import { useEffect, useMemo, useState } from 'react';
import { Search, Wrench, Filter, AlertCircle, RefreshCw } from 'lucide-react';
import { api } from '@/lib/api';
import type { Capability } from '@/types/api';
import { cn } from '@/lib/utils';

interface CapabilityDTO {
  name: string;
  description?: string;
  keywords?: string[];
  aliases?: string[];
  avg_latency_ms?: number;
  avg_cost?: number;
  preferred_worker_tags?: string[];
}

export function Tools() {
  const [caps, setCaps] = useState<CapabilityDTO[]>([]);
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState<string>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      // 后端实际返回 { capabilities: [...], task_types: [...] }
      const data = await api.capabilities() as unknown as
        | CapabilityDTO[]
        | { capabilities?: CapabilityDTO[]; task_types?: unknown[] };
      const list: CapabilityDTO[] = Array.isArray(data)
        ? (data as CapabilityDTO[])
        : (data?.capabilities ?? []);
      if (!Array.isArray(list)) {
        throw new Error('返回结构无 capabilities 数组');
      }
      setCaps(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setCaps([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const types = useMemo(() => {
    // 后端返回的 capability 不含 taskType，这里用首字母分组或统一为 'general'
    const s = new Set<string>(['general']);
    return ['all', ...Array.from(s)];
  }, []);

  const list = useMemo(
    () =>
      caps.filter((c) => {
        const matchQ =
          !q ||
          c.name.toLowerCase().includes(q.toLowerCase()) ||
          (c.description ?? '').toLowerCase().includes(q.toLowerCase());
        const matchF = filter === 'all' || filter === 'general';
        return matchQ && matchF;
      }),
    [caps, q, filter],
  );

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto">
        {/* 顶部操作栏 */}
        <div className="flex flex-wrap items-center gap-3 mb-5">
          <div className="flex-1 min-w-[220px] relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-fg2" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="搜索工具或能力…"
              className="w-full h-10 pl-10 pr-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[10px] text-[13px] text-fg0 placeholder:text-fg2 outline-none focus:border-cyan-500/40"
            />
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <Filter className="w-3.5 h-3.5 text-fg2" />
            {types.map((t) => (
              <button
                key={t}
                onClick={() => setFilter(t)}
                className={cn(
                  'h-7 px-2.5 text-[11.5px] rounded-full border transition-colors',
                  filter === t
                    ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300'
                    : 'border-[var(--border)] text-fg1 hover:text-fg0 hover:bg-white/5',
                )}
              >
                {t}
              </button>
            ))}
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="h-7 px-2.5 text-[11.5px] rounded-full border border-[var(--border)] text-fg1 hover:text-fg0 hover:bg-white/5 flex items-center gap-1 disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3 h-3', loading && 'animate-spin')} />
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mb-4 p-3 rounded-[8px] border border-red-500/30 bg-red-500/10 text-red-300 text-[12px] flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">加载工具失败</div>
              <div className="opacity-80 mt-0.5">{error}</div>
              <div className="text-fg2 mt-1">
                请确认后端 <code className="font-mono">app.py</code> 已启动在 8000 端口。
              </div>
            </div>
          </div>
        )}

        {/* 状态摘要 */}
        {!loading && !error && (
          <div className="text-[11px] text-fg2 mb-3">
            共 <span className="font-mono text-fg1">{caps.length}</span> 个能力（来自{' '}
            <code className="font-mono">/api/capabilities</code>）
          </div>
        )}

        {/* 卡片网格 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 stagger">
          {list.map((c) => (
            <div key={c.name} className="card p-4 hover:border-cyan-500/30 transition-colors">
              <div className="flex items-center gap-2.5 mb-2">
                <div className="w-8 h-8 rounded-[8px] flex items-center justify-center bg-[var(--bg-2)] border border-[var(--border)]">
                  <Wrench className="w-4 h-4 text-accent1" strokeWidth={1.6} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[13.5px] font-semibold text-fg0 font-mono truncate">
                    {c.name}
                  </div>
                  {c.preferred_worker_tags && c.preferred_worker_tags.length > 0 && (
                    <div className="text-[10.5px] text-fg2 font-mono truncate">
                      tags: {c.preferred_worker_tags.join(', ')}
                    </div>
                  )}
                </div>
              </div>
              {c.description && (
                <p className="text-[12px] text-fg1 line-clamp-3 leading-relaxed">
                  {c.description}
                </p>
              )}
              {(c.avg_latency_ms !== undefined || c.avg_cost !== undefined) && (
                <div className="mt-2 pt-2 border-t border-[var(--border)] flex gap-3 text-[10.5px] text-fg2 font-mono">
                  {c.avg_latency_ms !== undefined && (
                    <span>⏱ {Math.round(c.avg_latency_ms)}ms</span>
                  )}
                  {c.avg_cost !== undefined && (
                    <span>💰 {c.avg_cost.toFixed(2)}</span>
                  )}
                </div>
              )}
            </div>
          ))}
          {!loading && list.length === 0 && !error && (
            <div className="col-span-full text-center text-fg2 py-12 text-sm">
              没有匹配的工具
            </div>
          )}
        </div>
      </div>
    </div>
  );
}