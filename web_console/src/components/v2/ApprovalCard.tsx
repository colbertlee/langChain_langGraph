/**
 * ApprovalCard — v2.2.1
 *
 * 渲染当前 session 的 HITL 待审批卡片（来自 SSE `event: approval_required`）。
 * 每条卡片显示：
 *  - 工具名（高亮）
 *  - 拦截原因
 *  - 工具参数（code / query / subcommand 等）
 *  - v2.2.1 — Edit & Resume：点击"编辑参数"切换为 JSON textarea，可微调后批准
 *  - v2.2.1 — 倒计时：默认 300s 超时倒计时；归零时显示"已自动拒绝 (Timed out)"占位
 *  - 「允许」「拒绝」按钮；点击后调 /api/chat/approve 或 /api/chat/reject
 *
 * 数据流：
 *  - 父组件（ChatPage 侧栏）通过 useChatStore selector 拿当前 session 的卡片
 *  - 点击 resolve：先调 chatStore.resolveApproval 改 status，再调后端 API
 *  - 后端写入 HITLStore，下一次用户消息触发模型再次调用该工具时即按决议执行
 *
 * P1-5 — 拒绝/批准后自动续生成：
 *  - 后端响应里带 resume_url（GET /api/chat/{rid}/resume），前端订阅该 SSE 续生成流。
 *  - resume 流走 runAgentStreamResume / normalizeSseEvents 归一化后 push 到消息流。
 *  - 若后端未返回 resume_url 或用户主动 abort → 退化为"用户需手动发消息续生成"，UI 提示。
 */
import { useEffect, useMemo, useState } from 'react';
import {
  ShieldCheck,
  ShieldX,
  Loader2,
  AlertTriangle,
  Pencil,
  X,
  Clock,
  Hourglass,
} from 'lucide-react';
import { useChatStore, type ChatApprovalCard } from '@/stores/chatStore';
import { api } from '@/lib/api';
import { resumeAgentStream } from '@/lib/agentStreamResume';
import { normalizeSseEvents } from '@/lib/sseParser';
import { formatRelative } from '@/lib/utils';

export interface ApprovalCardProps {
  sessionId: string;
}

export function ApprovalCard({ sessionId }: ApprovalCardProps) {
  const cards = useChatStore((s) => s.approvalCards[sessionId] ?? []);
  const resolveApproval = useChatStore((s) => s.resolveApproval);
  const [busyId, setBusyId] = useState<string | null>(null);
  // P1-5 — resume 状态：让 UI 显示「正在自动续生成…」指示
  const [resumingId, setResumingId] = useState<string | null>(null);

  if (cards.length === 0) {
    return (
      <div className="text-[12px] text-fg2 italic">暂无待审批请求</div>
    );
  }

  /**
   * P1-5 — 后端响应带 resume_url 时自动订阅续生成流。
   * 事件归一化后 push 到 chatStore + agentEvents，让消息流平滑续接。
   * 失败/无 resume_url 时静默退化为「用户手动发消息续生成」。
   */
  const resumeIfAvailable = async (card: ChatApprovalCard, resumeUrl: string | undefined) => {
    if (!resumeUrl) return;
    setResumingId(card.id);
    const controller = new AbortController();
    try {
      for await (const ev of resumeAgentStream(card.id, card.sessionId, controller.signal)) {
        // 归一化为文本/工具事件并交给 chatStore
        const obj = (ev.dataObj ?? {}) as Record<string, unknown>;
        const rawType = (obj.type as string | undefined) ?? ev.event;
        const t = (rawType ?? '').toLowerCase();
        if (t === 'chunk' || t === 'token' || t === 'text') {
          const dataStr = typeof obj.data === 'string' ? obj.data : undefined;
          const contentStr = typeof obj.content === 'string' ? obj.content : undefined;
          const txt = dataStr ?? contentStr ?? '';
          if (txt) {
            useChatStore.getState().appendResumeText?.(card.sessionId, txt);
          }
        } else if (t === 'tool_start') {
          useChatStore.getState().appendResumeText?.(
            card.sessionId,
            `\n\n> 🔧 调用工具 \`${obj.name ?? ''}\`\n`,
          );
        } else if (t === 'tool_result') {
          useChatStore.getState().appendResumeText?.(
            card.sessionId,
            `\n> ✅ ${obj.name ?? 'tool'} 完成\n\n`,
          );
        } else if (t === 'thinking') {
          const dataStr = typeof obj.data === 'string' ? obj.data : undefined;
          if (dataStr) {
            useChatStore.getState().appendResumeText?.(
              card.sessionId,
              `\n\n<details><summary>🤔 思考过程</summary>\n\n${dataStr}\n\n</details>\n\n`,
            );
          }
        } else if (t === 'hitl_resumed') {
          useChatStore.getState().appendResumeText?.(
            card.sessionId,
            `\n\n> ▶️ 模型已恢复（${obj.phase === 'approved' ? '已批准' : '已拒绝'}）\n`,
          );
        } else if (t === 'error') {
          const dataStr = typeof obj.data === 'string' ? obj.data : undefined;
          const errMsg =
            dataStr ??
            (obj.error as string | undefined) ??
            '续生成失败';
          useChatStore.getState().appendResumeText?.(
            card.sessionId,
            `\n\n> ⚠️ 续生成失败：${errMsg}\n> 可手动发送任意消息让模型继续。\n`,
          );
        } else if (t === 'complete') {
          useChatStore.getState().appendResumeText?.(
            card.sessionId,
            `\n\n✅ **续生成完成**\n`,
          );
        }
      }
    } catch (e) {
      // 静默吞 abort；其它错误给用户一个提示
      if (!(e instanceof Error && e.name === 'AbortError')) {
        useChatStore.getState().appendResumeText?.(
          card.sessionId,
          `\n\n> ⚠️ Resume 流异常：${e instanceof Error ? e.message : String(e)}\n`,
        );
      }
    } finally {
      setResumingId(null);
      controller.abort();
    }
  };

  const handleApprove = async (card: ChatApprovalCard, editedArgs?: Record<string, unknown>) => {
    setBusyId(card.id);
    try {
      const res = await api.chatApprove({
        session_id: card.sessionId,
        request_id: card.id,
        tool_args: editedArgs ?? card.toolArgs,
        decided_by: 'user',
      });
      resolveApproval(card.sessionId, card.id, 'approved');
      // P1-5：后端响应里若带 resume_url，自动订阅续生成 SSE
      await resumeIfAvailable(card, res?.resume_url);
    } catch (e) {
      // 失败时也标记 rejected（前端兜底，避免卡住）
      resolveApproval(
        card.sessionId,
        card.id,
        'rejected',
        e instanceof Error ? e.message : 'approve API failed',
      );
    } finally {
      setBusyId(null);
    }
  };

  const handleReject = async (card: ChatApprovalCard, reason?: string) => {
    setBusyId(card.id);
    try {
      const res = await api.chatReject({
        session_id: card.sessionId,
        request_id: card.id,
        reason: reason || '用户主动拒绝',
        decided_by: 'user',
      });
      resolveApproval(card.sessionId, card.id, 'rejected', reason || '用户主动拒绝');
      // P1-5：同 approve，自动订阅续生成
      await resumeIfAvailable(card, res?.resume_url);
    } catch (e) {
      resolveApproval(
        card.sessionId,
        card.id,
        'rejected',
        e instanceof Error ? e.message : 'reject API failed',
      );
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="space-y-3">
      {cards.map((c) => (
        <ApprovalCardItem
          key={c.id}
          card={c}
          busy={busyId === c.id}
          resuming={resumingId === c.id}
          onApprove={(args) => handleApprove(c, args)}
          onReject={(reason) => handleReject(c, reason)}
        />
      ))}
    </div>
  );
}

interface ApprovalCardItemProps {
  card: ChatApprovalCard;
  busy: boolean;
  resuming: boolean;
  onApprove: (editedArgs?: Record<string, unknown>) => void;
  onReject: (reason?: string) => void;
}

function ApprovalCardItem({ card, busy, resuming, onApprove, onReject }: ApprovalCardItemProps) {
  const isResolved = card.status === 'approved' || card.status === 'rejected';
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState(() => JSON.stringify(card.toolArgs ?? {}, null, 2));
  const [editError, setEditError] = useState<string | null>(null);
  // v2.2.1 — 倒计时（默认 300s）
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (isResolved) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [isResolved]);

  // 超时秒数（从 createdAt + 5min 推断；后端 timeout_seconds 字段未来可透传）
  const TIMEOUT_SEC = 300;
  const elapsed = Math.max(0, Math.floor((now - card.createdAt) / 1000));
  const remaining = Math.max(0, TIMEOUT_SEC - elapsed);
  const timedOut = !isResolved && remaining <= 0;

  const parsedEdited = useMemo<Record<string, unknown> | null>(() => {
    if (!editing) return null;
    try {
      const v = JSON.parse(editedText);
      if (typeof v !== 'object' || v === null || Array.isArray(v)) {
        return null;
      }
      return v as Record<string, unknown>;
    } catch {
      return null;
    }
  }, [editing, editedText]);

  const handleStartEdit = () => {
    setEditing(true);
    setEditError(null);
  };

  const handleCancelEdit = () => {
    setEditing(false);
    setEditedText(JSON.stringify(card.toolArgs ?? {}, null, 2));
    setEditError(null);
  };

  const handleApproveClick = () => {
    if (editing) {
      // 编辑模式：先解析 JSON
      try {
        const v = JSON.parse(editedText);
        if (typeof v !== 'object' || v === null || Array.isArray(v)) {
          setEditError('参数必须是 JSON 对象');
          return;
        }
        onApprove(v as Record<string, unknown>);
      } catch (e) {
        setEditError(`JSON 解析失败: ${e instanceof Error ? e.message : 'invalid JSON'}`);
        return;
      }
    } else {
      onApprove();
    }
  };

  return (
    <div
      className="card p-3 relative overflow-hidden"
      style={{
        background: 'linear-gradient(180deg, rgba(245,158,11,0.08) 0%, var(--bg-1) 60%)',
        opacity: timedOut ? 0.55 : 1,
      }}
      data-testid="approval-card"
      data-card-status={card.status}
    >
      <div className="absolute left-0 top-0 bottom-0 w-[3px] bg-amber-500" />
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" strokeWidth={1.8} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-1.5 flex-wrap">
            <span className="badge badge-warn text-[10px]">
              {timedOut
                ? '已超时 (Timed out)'
                : isResolved
                ? card.status === 'approved'
                  ? '已允许'
                  : '已拒绝'
                : 'HITL · 待审批'}
            </span>
            <span className="text-[10px] text-fg2 font-mono flex items-center gap-0.5">
              <Clock className="w-2.5 h-2.5" />
              {formatRelative(card.createdAt)}
            </span>
            {!isResolved && (
              <span
                className="text-[10px] text-fg2 font-mono flex items-center gap-0.5"
                data-testid="approval-card-countdown"
              >
                <Hourglass className="w-2.5 h-2.5" />
                {remaining}s
              </span>
            )}
          </div>
          <div className="text-[13px] font-semibold text-fg0 mb-1">
            工具：<span className="font-mono text-accent1">{card.toolName}</span>
          </div>
          <div className="text-[12px] text-fg1 mb-2 break-words">{card.reason}</div>
          {card.toolArgs && Object.keys(card.toolArgs).length > 0 && !editing && (
            <pre
              className="font-mono text-[10.5px] text-fg1 bg-[var(--code-bg)] rounded-md p-2 overflow-x-auto mb-2"
              data-testid="approval-card-args"
            >
              {JSON.stringify(card.toolArgs, null, 2)}
            </pre>
          )}
          {editing && (
            <div className="mb-2" data-testid="approval-card-edit-area">
              <textarea
                value={editedText}
                onChange={(e) => {
                  setEditedText(e.target.value);
                  setEditError(null);
                }}
                rows={Math.max(4, Math.min(12, editedText.split('\n').length + 1))}
                className="w-full font-mono text-[10.5px] text-fg1 bg-[var(--code-bg)] border border-amber-500/40 rounded-md p-2 outline-none focus:border-amber-500"
                spellCheck={false}
              />
              {editError && (
                <div className="text-[10.5px] text-red-500 mt-1">{editError}</div>
              )}
              <div className="text-[10px] text-fg2 mt-1">
                提示：必须是合法 JSON 对象；空对象表示无参数。
              </div>
            </div>
          )}
          <div className="text-[10px] text-fg2 font-mono mb-2">
            session: {card.sessionId.slice(0, 8)} · id: {card.id.slice(0, 8)}
          </div>
          {!isResolved && !timedOut && (
            <div className="flex flex-wrap gap-2">
              <button
                disabled={busy || (editing && !parsedEdited)}
                onClick={handleApproveClick}
                data-testid="approval-card-approve"
                className="btn-primary h-8 px-3 text-[11.5px] disabled:opacity-50 flex items-center gap-1"
              >
                {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                {editing ? '使用修改后的参数执行' : '允许执行'}
              </button>
              <button
                disabled={busy}
                onClick={() => onReject()}
                data-testid="approval-card-reject"
                className="btn-ghost h-8 px-3 text-[11.5px] hover:!text-red-500 hover:!border-red-500/40 disabled:opacity-50 flex items-center gap-1"
              >
                {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldX className="w-3.5 h-3.5" />}
                拒绝
              </button>
              {/* P1-5：resuming 指示灯 */}
              {resuming && (
                <span
                  className="text-[10.5px] text-cyan-400 flex items-center gap-1 ml-1"
                  data-testid="approval-card-resuming"
                >
                  <Loader2 className="w-3 h-3 animate-spin" />
                  模型正在恢复生成…
                </span>
              )}
              {editing ? (
                <button
                  disabled={busy}
                  onClick={handleCancelEdit}
                  data-testid="approval-card-cancel-edit"
                  className="btn-ghost h-8 px-2 text-[11px] flex items-center gap-1"
                >
                  <X className="w-3 h-3" /> 取消编辑
                </button>
              ) : (
                <button
                  disabled={busy}
                  onClick={handleStartEdit}
                  data-testid="approval-card-edit"
                  className="btn-ghost h-8 px-2 text-[11px] flex items-center gap-1"
                >
                  <Pencil className="w-3 h-3" /> 编辑参数
                </button>
              )}
            </div>
          )}
          {(isResolved || timedOut) && (
            <div
              className="text-[11px] italic mt-1"
              data-testid="approval-card-resolved"
              style={{
                color: card.status === 'approved' ? 'rgb(52,211,153)' : 'rgb(248,113,113)',
              }}
            >
              {card.status === 'approved'
                ? '✅ 已允许；模型将在下一轮对话中重新执行该工具。'
                : timedOut
                ? '⏰ 已超时自动拒绝；模型将收到取消消息。'
                : `❌ 已拒绝${card.rejectReason ? `（${card.rejectReason}）` : ''}；模型将收到取消消息。`}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
