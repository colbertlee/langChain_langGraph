/**
 * v2.0 slim — TokenUsageWidget
 *
 * 通过 api.telemetry() 拉取后端 /telemetry/snapshot。
 */
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export function TokenUsageWidget() {
  const [val, setVal] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.telemetry?.()
      .then((snap) => {
        if (cancelled) return;
        setVal(snap?.gauges?.tokens_total ?? null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 p-4">
      <div className="text-xs text-slate-500">Token 用量</div>
      <div className="text-2xl font-semibold mt-1">{val ?? '—'}</div>
    </div>
  );
}