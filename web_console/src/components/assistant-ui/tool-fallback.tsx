import { type FC, useState } from 'react';
import { ChevronDown, ChevronRight, Copy, CheckCircle2, AlertCircle, Loader2, Wrench } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ToolFallbackProps {
  toolName: string;
  args?: Record<string, unknown>;
  result?: unknown;
  status?: { type: string };
}

export const ToolCallCard: FC<ToolFallbackProps> = ({ toolName, args, result, status }) => {
  const [open, setOpen] = useState(false);
  const running = status?.type === 'running';
  const isError = status?.type === 'incomplete' || status?.type === 'failed';
  const Icon = running
    ? Loader2
    : isError
      ? AlertCircle
      : result
        ? CheckCircle2
        : Wrench;
  const color = running
    ? 'text-[var(--accent-1)]'
    : isError
      ? 'text-[var(--danger)]'
      : 'text-[var(--success)]';

  return (
    <div className="relative my-2 rounded-[10px] overflow-hidden border border-[var(--border)] bg-[rgba(255,255,255,0.02)]">
      <div
        className="absolute left-0 top-0 bottom-0 w-[2px]"
        style={{
          background: running
            ? 'linear-gradient(180deg, #06B6D4, transparent)'
            : isError
              ? 'linear-gradient(180deg, #F43F5E, transparent)'
              : 'linear-gradient(180deg, #10B981, transparent)',
        }}
      />
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2.5 px-3.5 py-2.5 text-left"
      >
        <Icon className={cn('w-3.5 h-3.5 shrink-0', color, running && 'animate-spin')} strokeWidth={2} />
        <span className="font-mono text-[12.5px] text-fg0 font-medium">{toolName}</span>
        <span className="flex-1" />
        {open ? <ChevronDown className="w-3.5 h-3.5 text-fg2" /> : <ChevronRight className="w-3.5 h-3.5 text-fg2" />}
      </button>
      {open && (
        <div className="border-t border-[var(--border)] px-3.5 py-3 space-y-3 bg-[rgba(0,0,0,0.2)]">
          <Block label="Arguments" text={stringify(args)} />
          {result !== undefined && result !== '' && (
            <Block label="Result" text={typeof result === 'string' ? result : stringify(result)} />
          )}
        </div>
      )}
    </div>
  );
};

const Block: FC<{ label: string; text: string }> = ({ label, text }) => (
  <div>
    <div className="flex items-center justify-between mb-1.5">
      <span className="text-[10.5px] uppercase tracking-wider text-fg2 font-mono">{label}</span>
      <button
        onClick={(e) => {
          e.stopPropagation();
          navigator.clipboard.writeText(text).catch(() => {});
        }}
        className="p-1 rounded text-fg2 hover:text-fg0 hover:bg-white/5"
        title="复制"
      >
        <Copy className="w-3 h-3" />
      </button>
    </div>
    <pre className="font-mono text-[11.5px] text-fg1 bg-[rgba(0,0,0,0.4)] rounded-md p-2.5 overflow-x-auto max-h-64 whitespace-pre-wrap break-all">
      {text}
    </pre>
  </div>
);

function stringify(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2);
  } catch {
    return String(v);
  }
}
