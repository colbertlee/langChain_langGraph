import { useEffect, useState } from 'react';
import { Brain, Send, Trash2, AlertCircle, RefreshCw, Sparkles } from 'lucide-react';
import { api, type MemoryItem } from '@/lib/api';
import { cn } from '@/lib/utils';

export function Memory() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [toast, setToast] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.memoryList(200);
      setItems(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  // 自动消失的 toast
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  const submit = async () => {
    const text = draft.trim();
    if (!text) return;
    if (text.length > 2000) {
      setToast({ kind: 'err', text: '内容不能超过 2000 字' });
      return;
    }
    setSubmitting(true);
    try {
      await api.memoryAdd(text);
      setDraft('');
      setToast({ kind: 'ok', text: '已记住 ✓' });
      await load();
    } catch (e) {
      setToast({ kind: 'err', text: e instanceof Error ? e.message : String(e) });
    } finally {
      setSubmitting(false);
    }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter 发送；Shift+Enter 换行
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const del = async (id: number) => {
    if (deletingId !== null) return;
    if (!confirm('删除这条记忆？')) return;
    setDeletingId(id);
    try {
      await api.memoryDelete(id);
      setToast({ kind: 'ok', text: '已删除' });
      await load();
    } catch (e) {
      setToast({ kind: 'err', text: e instanceof Error ? e.message : String(e) });
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto space-y-4 stagger">
        {/* 标题 + 统计 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-accent1" />
            <h2 className="text-[16px] font-semibold">对话式记忆</h2>
            <span className="text-[11px] text-fg2 font-mono">
              共 {total} 条
            </span>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="text-[11.5px] text-fg2 hover:text-fg1 flex items-center gap-1 disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>

        {/* 提示卡片 */}
        <div className="card p-4 border-cyan-500/20 bg-cyan-500/[0.04]">
          <div className="flex items-start gap-2.5">
            <Sparkles className="w-4 h-4 text-cyan-400 mt-0.5 shrink-0" />
            <div className="text-[12.5px] text-fg1 leading-relaxed">
              <div>
                在下方输入任意你想让 Agent 记住的内容，按{' '}
                <kbd className="px-1.5 py-0.5 rounded bg-white/10 text-[11px] font-mono">Enter</kbd>{' '}
                发送。
              </div>
              <div className="text-fg2 mt-1 text-[11.5px]">
                例如：<span className="font-mono opacity-80">"我每天早上 8 点起床"</span>、
                <span className="font-mono opacity-80 ml-1">"公司是 MiniMax"</span>、
                <span className="font-mono opacity-80 ml-1">"偏好用中文回答"</span>……
              </div>
              <div className="text-fg2 mt-1 text-[11.5px]">
                系统会自动保存到全局记忆，下次对话 Agent 会自动检索相关条目。
              </div>
            </div>
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="card p-3 border-red-500/30 bg-red-500/10 text-red-300 text-[12px] flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">加载失败</div>
              <div className="opacity-80 mt-0.5">{error}</div>
              <div className="text-fg2 mt-1">
                请确认后端 <code className="font-mono">app.py</code> 已启动在 8000 端口。
              </div>
            </div>
          </div>
        )}

        {/* 输入框 */}
        <div className="card p-4">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={'输入一条记忆…（Enter 发送，Shift+Enter 换行）'}
            rows={3}
            disabled={submitting}
            className="w-full resize-y min-h-[80px] bg-[var(--bg-1)] border border-[var(--border)] rounded-[10px] text-[13px] text-fg0 placeholder:text-fg2 outline-none focus:border-cyan-500/40 p-3"
          />
          <div className="mt-2 flex items-center justify-between">
            <span className="text-[10.5px] text-fg2 font-mono">
              {draft.length} / 2000
            </span>
            <button
              onClick={submit}
              disabled={submitting || !draft.trim()}
              className="btn-primary h-9 px-4 disabled:opacity-50"
            >
              <Send className="w-3.5 h-3.5" />
              {submitting ? '保存中…' : '记住'}
            </button>
          </div>
        </div>

        {/* 记忆列表 */}
        <div className="space-y-2">
          {loading && items.length === 0 && (
            <div className="text-center text-fg2 py-8 text-[13px]">加载中…</div>
          )}

          {!loading && items.length === 0 && !error && (
            <div className="card p-8 text-center text-fg2">
              <Brain className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <div className="text-[13px]">还没有记忆</div>
              <div className="text-[11.5px] mt-1 opacity-70">
                在上方输入第一条，让 Agent 记住吧
              </div>
            </div>
          )}

          {items.map((it) => (
            <div
              key={it.id}
              className="card p-3.5 group hover:border-cyan-500/30 transition-colors"
            >
              <div className="flex items-start gap-3">
                <div className="w-7 h-7 rounded-[8px] flex items-center justify-center bg-[var(--bg-2)] border border-[var(--border)] shrink-0 mt-0.5">
                  <Brain className="w-3.5 h-3.5 text-accent1" strokeWidth={1.6} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] text-fg1 whitespace-pre-wrap break-words leading-relaxed">
                    {it.content}
                  </div>
                  <div className="mt-1.5 text-[10.5px] text-fg2 font-mono flex items-center gap-2 flex-wrap">
                    <span>#{it.id}</span>
                    {it.memory_type && <span>· {it.memory_type}</span>}
                    {it.importance !== undefined && (
                      <span>· 重要度 {it.importance}</span>
                    )}
                    {it.created_at && (
                      <span>
                        · {new Date(
                          typeof it.created_at === 'number'
                            ? it.created_at * (it.created_at > 1e12 ? 1 : 1000)
                            : Date.parse(it.created_at),
                        ).toLocaleString('zh-CN')}
                      </span>
                    )}
                  </div>
                </div>
                <button
                  onClick={() => del(it.id)}
                  disabled={deletingId === it.id}
                  className="text-fg2 hover:text-red-400 disabled:opacity-40 p-1.5 rounded-md hover:bg-white/5 transition-colors opacity-0 group-hover:opacity-100"
                  title="删除"
                  aria-label="删除"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div
          className={cn(
            'fixed bottom-6 right-6 px-4 py-2.5 rounded-[10px] text-[13px] shadow-lg border z-50',
            toast.kind === 'ok'
              ? 'bg-emerald-500/15 border-emerald-500/30 text-emerald-300'
              : 'bg-red-500/15 border-red-500/30 text-red-300',
          )}
        >
          {toast.text}
        </div>
      )}
    </div>
  );
}