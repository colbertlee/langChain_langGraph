/**
 * v2.0 slim — ErrorRateWidget
 *
 * 通过 api.telemetry() 拉取错误计数器。
 */
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export function ErrorRateWidget() {
  const [errors, setErrors] = useState<number | null>(null);
  const [total, setTotal] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.telemetry?.()
      .then((snap) => {
        if (cancelled) return;
        setErrors(snap?.counters?.errors_total ?? null);
        setTotal(snap?.counters?.requests_total ?? null);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const rate = errors != null && total ? ((errors / total) * 100).toFixed(2) : '—';

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 p-4">
      <div className="text-xs text-slate-500">错误率</div>
      <div className="text-2xl font-semibold mt-1">{rate}%</div>
      <div className="text-xs text-slate-400 mt-1">
        {errors ?? '—'} / {total ?? '—'}
      </div>
    </div>
  );
}