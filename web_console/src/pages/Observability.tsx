import { useEffect, useState } from 'react';
import { Activity, AlertCircle, Info, AlertTriangle, BarChart3 } from 'lucide-react';
import { api } from '@/lib/api';
import type { ObsEvent, TraceSpan } from '@/types/api';
import { cn, formatTime } from '@/lib/utils';

export function Observability() {
  const [events, setEvents] = useState<ObsEvent[]>([]);
  const [traces, setTraces] = useState<TraceSpan[]>([]);
  const [metrics, setMetrics] = useState<string>('');
  const [tab, setTab] = useState<'events' | 'traces' | 'metrics'>('events');

  useEffect(() => {
    let cancel = false;
    const load = async () => {
      try {
        const [e, t] = await Promise.all([api.events(50), api.traces(50)]);
        if (!cancel) {
          setEvents(e);
          setTraces(t);
        }
      } catch {
        if (!cancel) {
          setEvents(MOCK_EVENTS);
          setTraces(MOCK_TRACES);
        }
      }
    };
    load();
    const t = window.setInterval(load, 5000);
    api.metrics()
      .then(setMetrics)
      .catch(() =>
        setMetrics(
          '# HELP agent_requests_total Total agent requests\n# TYPE counter\nagent_requests_total 1284\n',
        ),
      );
    return () => {
      cancel = true;
      window.clearInterval(t);
    };
  }, []);

  return (
    <div className="h-full flex flex-col">
      <div className="px-6 pt-4 pb-2 flex items-center gap-1 border-b border-[var(--border)]">
        {[
          { k: 'events', label: 'Events', icon: Activity },
          { k: 'traces', label: 'Traces', icon: BarChart3 },
          { k: 'metrics', label: 'Metrics', icon: AlertCircle },
        ].map((it) => (
          <button
            key={it.k}
            onClick={() => setTab(it.k as 'events' | 'traces' | 'metrics')}
            className={cn(
              'h-9 px-3.5 text-[13px] font-medium rounded-[10px] flex items-center gap-1.5 transition-colors',
              tab === it.k
                ? 'bg-white/[0.06] text-fg0'
                : 'text-fg1 hover:text-fg0 hover:bg-white/[0.03]',
            )}
          >
            <it.icon className="w-3.5 h-3.5" />
            {it.label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-6">
        {tab === 'events' && <EventsView events={events} />}
        {tab === 'traces' && <TracesView traces={traces} />}
        {tab === 'metrics' && <MetricsView text={metrics} />}
      </div>
    </div>
  );
}

function EventsView({ events }: { events: ObsEvent[] }) {
  return (
    <div className="max-w-5xl mx-auto card overflow-hidden">
      <div className="font-mono text-[12px]">
        {events.map((e) => {
          const Icon = e.level === 'error' ? AlertCircle : e.level === 'warn' ? AlertTriangle : Info;
          const color =
            e.level === 'error'
              ? 'border-l-danger text-danger'
              : e.level === 'warn'
                ? 'border-l-warn text-warn'
                : 'border-l-accent1 text-fg1';
          return (
            <div
              key={e.id}
              className={cn(
                'flex items-start gap-3 px-4 py-2 border-b border-[var(--border)] border-l-[3px]',
                color,
              )}
            >
              <span className="text-fg2 shrink-0">{formatTime(e.ts)}</span>
              <Icon className="w-3.5 h-3.5 mt-[2px] shrink-0" />
              <span className="text-fg2 shrink-0">[{e.source}]</span>
              <span className="text-fg0 break-all">{e.message}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TracesView({ traces }: { traces: TraceSpan[] }) {
  return (
    <div className="max-w-5xl mx-auto space-y-2 stagger">
      {traces.map((s) => {
        const dur = s.endedAt ? s.endedAt - s.startedAt : 0;
        return (
          <div key={s.id} className="card p-3.5 flex items-center gap-3">
            <div
              className={cn(
                'w-1 h-8 rounded-full',
                s.status === 'error' ? 'bg-danger' : 'bg-accent1',
              )}
            />
            <div className="flex-1 min-w-0">
              <div className="font-mono text-[13px] text-fg0 truncate">{s.name}</div>
              <div className="text-[11px] text-fg2 font-mono">
                {formatTime(s.startedAt)} · {dur}ms · {s.id}
              </div>
            </div>
            <div className="text-[11px] text-fg2 font-mono shrink-0">{dur}ms</div>
          </div>
        );
      })}
    </div>
  );
}

function MetricsView({ text }: { text: string }) {
  return (
    <div className="max-w-5xl mx-auto card p-4">
      <pre className="font-mono text-[12px] text-fg1 whitespace-pre-wrap break-all">{text || '// loading…'}</pre>
    </div>
  );
}

const MOCK_EVENTS: ObsEvent[] = [
  { id: '1', level: 'info', source: 'agent', message: 'started run session=demo-1', ts: Date.now() - 1000 },
  { id: '2', level: 'debug', source: 'router', message: 'selected agent=researcher-01 confidence=0.87', ts: Date.now() - 2000 },
  { id: '3', level: 'info', source: 'rag', message: 'loaded 12 chunks from knowledge_base/', ts: Date.now() - 3000 },
  { id: '4', level: 'warn', source: 'tool', message: 'web_search timeout, retrying (2/3)', ts: Date.now() - 5000 },
  { id: '5', level: 'error', source: 'tool', message: 'run_code failed: IndentationError', ts: Date.now() - 8000 },
  { id: '6', level: 'info', source: 'agent', message: 'stream finished, 412 tokens', ts: Date.now() - 9000 },
];

const MOCK_TRACES: TraceSpan[] = [
  { id: 'sp-1', name: 'agent.run', startedAt: Date.now() - 1000, endedAt: Date.now() - 100, status: 'ok' },
  { id: 'sp-2', parentId: 'sp-1', name: 'router.decide', startedAt: Date.now() - 950, endedAt: Date.now() - 900, status: 'ok' },
  { id: 'sp-3', parentId: 'sp-1', name: 'rag.retrieve', startedAt: Date.now() - 900, endedAt: Date.now() - 600, status: 'ok' },
  { id: 'sp-4', parentId: 'sp-1', name: 'llm.stream', startedAt: Date.now() - 600, endedAt: Date.now() - 100, status: 'ok' },
];
