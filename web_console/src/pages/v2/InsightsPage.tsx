/**
 * v2.0 slim — InsightsPage
 *
 * 精简后仅保留 3 个 widget：
 *   1. TokenUsageWidget    来自 telemetry.snapshot().gauges
 *   2. ErrorRateWidget     来自 telemetry.snapshot().counters
 *   3. TraceListTable      来自 telemetry.snapshot().recent_spans
 */
import { TokenUsageWidget } from '@/components/v2/TokenUsageWidget';
import { ErrorRateWidget } from '@/components/v2/ErrorRateWidget';
import { TraceListTable } from '@/components/v2/TraceListTable';

export function InsightsPage() {
  return (
    <div className="p-4 space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <TokenUsageWidget />
        <ErrorRateWidget />
      </div>
      <TraceListTable />
    </div>
  );
}
