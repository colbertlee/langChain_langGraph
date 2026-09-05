/**
 * v2.0 slim — TraceListTable
 *
 * 显示最近 20 条 span（来自 telemetry.snapshot().recent_spans）。
 */
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

interface Span {
  name: string;
  duration_ms?: number;
  status?: string;
}

export function TraceListTable() {
  const [spans, setSpans] = useState<Span[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.telemetry?.()
      .then((snap) => {
        if (cancelled) return;
        setSpans(snap?.recent_spans ?? []);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 p-4">
      <div className="text-sm font-semibold mb-2">最近 Trace</div>
      <table className="w-full text-xs">
        <thead className="text-left text-slate-500">
          <tr>
            <th className="py-1">Name</th>
            <th className="py-1">Duration</th>
            <th className="py-1">Status</th>
          </tr>
        </thead>
        <tbody>
          {spans.length === 0 ? (
            <tr>
              <td colSpan={3} className="py-2 text-slate-400">暂无 Trace</td>
            </tr>
          ) : (
            spans.map((s, i) => (
              <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1 font-mono">{s.name}</td>
                <td className="py-1">{s.duration_ms?.toFixed(1) ?? '—'} ms</td>
                <td className="py-1">{s.status ?? '—'}</td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}