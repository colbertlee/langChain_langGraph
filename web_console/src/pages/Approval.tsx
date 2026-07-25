import { useEffect, useState } from 'react';
import { ShieldCheck, ShieldX, Loader2, Inbox } from 'lucide-react';
import { api } from '@/lib/api';
import type { PendingApproval } from '@/types/api';
import { formatRelative } from '@/lib/utils';

export function Approval() {
  const [list, setList] = useState<PendingApproval[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const data = await api.hitlPending();
      setList(data);
    } catch {
      setList(MOCK);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 6000);
    return () => window.clearInterval(t);
  }, []);

  const decide = async (id: string, decision: 'approve' | 'reject') => {
    setBusy(id);
    try {
      await api.hitlDecide(id, decision);
      setList((l) => l.filter((x) => x.id !== id));
    } catch {
      // demo 模式直接移除
      setList((l) => l.filter((x) => x.id !== id));
    } finally {
      setBusy(null);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-accent1 animate-spin" />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        {list.length === 0 ? (
          <div className="h-[60vh] flex flex-col items-center justify-center text-center">
            <div className="w-16 h-16 rounded-2xl bg-[var(--bg-1)] border border-[var(--border)] flex items-center justify-center mb-4">
              <Inbox className="w-7 h-7 text-fg2" strokeWidth={1.5} />
            </div>
            <h3 className="text-[16px] font-semibold mb-1">当前没有待审批请求</h3>
            <p className="text-fg2 text-[13px]">Agent 在执行高风险操作时会暂停在这里等待你的决定</p>
          </div>
        ) : (
          <div className="space-y-3 stagger">
            {list.map((p) => (
              <div
                key={p.id}
                className="card p-4 relative overflow-hidden"
                style={{
                  background:
                    'linear-gradient(180deg, rgba(245,158,11,0.06) 0%, var(--bg-1) 50%)',
                }}
              >
                <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-warn" />
                <div className="flex items-start gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="badge badge-warn">HITL · 待审批</span>
                      <span className="text-[10.5px] text-fg2 font-mono">
                        {formatRelative(p.createdAt)}
                      </span>
                    </div>
                    <div className="text-[15px] font-semibold text-fg0 mb-1">
                      工具调用：<span className="font-mono text-accent1">{p.toolName}</span>
                    </div>
                    <div className="text-[13px] text-fg1 mb-2">{p.reason}</div>
                    {p.args && (
                      <pre className="font-mono text-[11.5px] text-fg1 bg-[rgba(0,0,0,0.4)] rounded-md p-2.5 overflow-x-auto">
                        {JSON.stringify(p.args, null, 2)}
                      </pre>
                    )}
                    <div className="mt-2 text-[10.5px] text-fg2 font-mono">
                      session: {p.sessionId} · id: {p.id}
                    </div>
                  </div>
                  <div className="flex flex-col gap-2 shrink-0">
                    <button
                      disabled={busy === p.id}
                      onClick={() => decide(p.id, 'approve')}
                      className="btn-primary h-9 px-4 text-[12.5px] disabled:opacity-50"
                    >
                      <ShieldCheck className="w-4 h-4" />
                      批准
                    </button>
                    <button
                      disabled={busy === p.id}
                      onClick={() => decide(p.id, 'reject')}
                      className="btn-ghost h-9 px-4 text-[12.5px] hover:!text-danger hover:!border-danger/40 disabled:opacity-50"
                    >
                      <ShieldX className="w-4 h-4" />
                      拒绝
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

const MOCK: PendingApproval[] = [
  {
    id: 'req-001',
    sessionId: 'demo-1',
    toolName: 'run_code',
    reason: 'Agent 想要执行 Python 代码：os.system("rm -rf /tmp/cache")',
    args: { code: 'os.system("rm -rf /tmp/cache")', lang: 'python' },
    createdAt: Date.now() - 120_000,
  },
  {
    id: 'req-002',
    sessionId: 'demo-2',
    toolName: 'github_push',
    reason: 'Agent 想要推送到 main 分支（保护分支）',
    args: { repo: 'colbertlee/langChain_langGraph', branch: 'main', files: 3 },
    createdAt: Date.now() - 30_000,
  },
];
