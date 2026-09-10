/**
 * AgentExecutionGraph — v2.2.3
 *
 * 渲染当前 Assistant 响应卡片下方的"Agent 协作过程"折叠面板：
 *  - 监听后端 SSE `event: agent_switch` 事件，逐节点追加（如 Supervisor ➔ rag_worker ➔ code_worker）；
 *  - 每个节点展示：Worker 名（中文标签 + 颜色）、切换原因 (reason)、与上一节点的耗时；
 *  - 当某节点触发 HITL（如 code_worker 调用 python_interpreter）时，会在节点下方
 *    自动嵌套渲染一个 **迷你** ApprovalCard（CompactApprovalCard），支持 Edit & Resume；
 *  - 当收到 `event: agent_done` 时，附加 "流程结束" 摘要节点；
 *  - 折叠面板默认收起；展开后展示完整节点链。
 *
 * 数据来源：
 *  - chatStore.agentEvents[sessionId] —— 持久化的事件数组，F5 后仍能恢复。
 *  - chatStore.approvalCards[sessionId] —— 嵌套的审批卡片数据；按 requestId 关联。
 *
 * 设计要点：
 *  - 与 v2.2.1 的侧栏 ApprovalCard 完全分离：侧栏仍是"全 session 待审批列表"，
 *    这里只渲染"与本次 Assistant 消息直接相关"的那部分卡片，避免重复。
 *  - 节点颜色按 Worker 类型编码：supervisor=slate、research=blue、code=violet、rag=emerald、FINISH=amber。
 *  - 与 assistant-ui 解耦：直接读 zustand，可在 ChatPage / 任意 assistant 卡片下挂载。
 */
import { useMemo, useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  GitBranch,
  Sparkles,
  Cpu,
  Search,
  Database,
  CheckCircle2,
  Loader2,
  ShieldCheck,
  ShieldX,
  Pencil,
  Clock,
  AlertTriangle,
} from 'lucide-react';
import { useChatStore, type ChatAgentEvent, type ChatApprovalCard } from '@/stores/chatStore';
import { api } from '@/lib/api';
import { formatRelative } from '@/lib/utils';

export interface AgentExecutionGraphProps {
  /** 当前消息所属 session id */
  sessionId: string;
  /** 可选：把节点链绑定到某条 messageId（默认由 props 决定） */
  messageId?: string;
  /** 默认是否展开（默认 false —— 折叠不抢眼） */
  defaultExpanded?: boolean;
}

/** Worker 名的中文展示 + 图标 / 颜色映射 */
function getAgentMeta(agent: string): {
  label: string;
  short: string;
  icon: React.ReactNode;
  cls: string;
  isTerminal?: boolean;
} {
  if (agent === 'supervisor' || agent === 'Supervisor') {
    return {
      label: 'Supervisor',
      short: 'SUP',
      icon: <Sparkles className="w-3 h-3" />,
      cls: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
    };
  }
  if (agent === 'research_worker') {
    return {
      label: '研究 Worker',
      short: 'RSC',
      icon: <Search className="w-3 h-3" />,
      cls: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
    };
  }
  if (agent === 'code_worker') {
    return {
      label: '代码 Worker',
      short: 'COD',
      icon: <Cpu className="w-3 h-3" />,
      cls: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
    };
  }
  if (agent === 'rag_worker') {
    return {
      label: 'RAG Worker',
      short: 'RAG',
      icon: <Database className="w-3 h-3" />,
      cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    };
  }
  if (agent === 'FINISH') {
    return {
      label: '流程结束',
      short: 'FIN',
      icon: <CheckCircle2 className="w-3 h-3" />,
      cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
      isTerminal: true,
    };
  }
  // 兜底
  return {
    label: agent,
    short: agent.slice(0, 3).toUpperCase(),
    icon: <GitBranch className="w-3 h-3" />,
    cls: 'bg-fg1/10 text-fg1 border-fg2/30',
  };
}

/** 把毫秒数格式化为 "1.2s" / "350ms" */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function AgentExecutionGraph({
  sessionId,
  defaultExpanded = false,
}: AgentExecutionGraphProps) {
  const events = useChatStore((s) => s.agentEvents[sessionId] ?? []);
  const [expanded, setExpanded] = useState(defaultExpanded);

  if (events.length === 0) {
    return null; // 无轨迹不渲染
  }

  // 把 switch 事件 + 末尾可选 done 事件整理为统一列表（store 里 type='done' 也已混入）
  const display = useMemo(() => events, [events]);

  return (
    <div
      className="mt-3 border border-[var(--border)] rounded-md bg-[var(--bg-1)]/60 overflow-hidden"
      data-testid="agent-execution-graph"
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-[var(--bg-2)]/40 transition-colors"
        data-testid="agent-execution-graph-toggle"
      >
        <span className="flex items-center gap-2 text-[11.5px] font-semibold text-fg1">
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-fg2" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5 text-fg2" />
          )}
          <GitBranch className="w-3.5 h-3.5 text-accent1" />
          Agent 协作过程
          <span
            className="text-[10px] font-mono text-fg2 ml-1"
            data-testid="agent-execution-graph-count"
          >
            {display.length} 节点
          </span>
        </span>
        <span className="text-[10px] text-fg2 font-mono">
          {expanded ? '收起' : '展开'}
        </span>
      </button>
      {expanded && (
        <div
          className="px-3 pb-3 pt-1 space-y-1"
          data-testid="agent-execution-graph-list"
        >
          {display.map((ev, idx) => (
            <AgentNodeRow
              key={ev.id}
              event={ev}
              index={idx}
              sessionId={sessionId}
              isLast={idx === display.length - 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface AgentNodeRowProps {
  event: ChatAgentEvent;
  index: number;
  sessionId: string;
  isLast: boolean;
}

function AgentNodeRow({ event, sessionId, index }: AgentNodeRowProps) {
  const meta = getAgentMeta(event.agent);
  const isDone = event.type === 'done' || meta.isTerminal;

  return (
    <div className="relative pl-5" data-testid="agent-node" data-agent={event.agent}>
      {/* 节点连接线 */}
      <div className="absolute left-1.5 top-0 bottom-0 w-px bg-[var(--border)]" />
      <div
        className={`absolute left-1.5 top-2 w-px h-[calc(100%-8px)] ${
          isDone ? 'bg-amber-500/40' : 'bg-[var(--border)]'
        }`}
      />
      <div
        className={`absolute left-0 top-1.5 w-3 h-3 rounded-full border-2 ${
          isDone
            ? 'bg-amber-500/30 border-amber-500'
            : 'bg-[var(--bg-1)] border-accent1'
        } flex items-center justify-center`}
      >
        {!isDone && <div className="w-1 h-1 rounded-full bg-accent1" />}
      </div>
      <div className="flex items-start gap-2 py-1">
        <span
          className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-mono rounded border ${meta.cls}`}
          data-testid="agent-node-badge"
        >
          {meta.icon}
          {meta.short}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap text-[11.5px]">
            <span className="font-semibold text-fg0">{meta.label}</span>
            {typeof event.durationMs === 'number' && event.durationMs > 0 && (
              <span
                className="text-[10px] font-mono text-fg2 inline-flex items-center gap-0.5"
                data-testid="agent-node-duration"
              >
                <Clock className="w-2.5 h-2.5" />
                {formatDuration(event.durationMs)}
              </span>
            )}
            {isDone && (
              <span className="text-[10px] font-mono text-amber-400 inline-flex items-center gap-0.5">
                <CheckCircle2 className="w-2.5 h-2.5" />
                结束
              </span>
            )}
          </div>
          {event.reason && event.type === 'switch' && (
            <div
              className="text-[11px] text-fg2 mt-0.5 break-words"
              data-testid="agent-node-reason"
            >
              {event.reason}
            </div>
          )}
          {event.requestId && (
            <CompactApprovalCard
              sessionId={sessionId}
              requestId={event.requestId}
            />
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * CompactApprovalCard — AgentExecutionGraph 节点下嵌套的精简审批组件
 *
 * 与侧栏 ApprovalCard 的区别：
 *  - 体积更小（不重复显示 session_id / 倒计时等元数据）
 *  - 仅展示与当前节点关联的那张卡（按 requestId 过滤）
 *  - 支持 Edit & Resume / Approve / Reject
 */
interface CompactApprovalCardProps {
  sessionId: string;
  requestId: string;
}

function CompactApprovalCard({ sessionId, requestId }: CompactApprovalCardProps) {
  const card = useChatStore((s) =>
    (s.approvalCards[sessionId] ?? []).find((c) => c.id === requestId),
  );
  const resolveApproval = useChatStore((s) => s.resolveApproval);
  const [editing, setEditing] = useState(false);
  const [editedText, setEditedText] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);

  if (!card) {
    // store 里可能还没落地（agent_switch 与 approval_required 事件几乎同时到达，
    // 但 store 是 setState 批处理的；UI 应优雅降级）
    return (
      <div
        className="mt-1.5 ml-1 px-2 py-1.5 rounded border border-amber-500/30 bg-amber-500/10 text-[10.5px] text-amber-300 inline-flex items-center gap-1"
        data-testid="agent-node-approval-pending"
      >
        <Loader2 className="w-3 h-3 animate-spin" />
        等待审批数据回填… (requestId: {requestId.slice(0, 8)})
      </div>
    );
  }

  const isResolved = card.status === 'approved' || card.status === 'rejected';

  const handleApprove = async (editedArgs?: Record<string, unknown>) => {
    setBusy(true);
    try {
      await api.chatApprove({
        session_id: card.sessionId,
        request_id: card.id,
        tool_args: editedArgs ?? card.toolArgs,
        decided_by: 'user',
      });
      resolveApproval(card.sessionId, card.id, 'approved');
    } catch (e) {
      resolveApproval(
        card.sessionId,
        card.id,
        'rejected',
        e instanceof Error ? e.message : 'approve API failed',
      );
    } finally {
      setBusy(false);
    }
  };

  const handleReject = async () => {
    setBusy(true);
    try {
      await api.chatReject({
        session_id: card.sessionId,
        request_id: card.id,
        reason: '用户主动拒绝',
        decided_by: 'user',
      });
      resolveApproval(card.sessionId, card.id, 'rejected', '用户主动拒绝');
    } catch (e) {
      resolveApproval(
        card.sessionId,
        card.id,
        'rejected',
        e instanceof Error ? e.message : 'reject API failed',
      );
    } finally {
      setBusy(false);
    }
  };

  const startEdit = () => {
    setEditedText(JSON.stringify(card.toolArgs ?? {}, null, 2));
    setEditing(true);
    setEditError(null);
  };

  const finishEdit = () => {
    try {
      const v = JSON.parse(editedText);
      if (typeof v !== 'object' || v === null || Array.isArray(v)) {
        setEditError('参数必须是 JSON 对象');
        return;
      }
      void handleApprove(v as Record<string, unknown>);
    } catch (e) {
      setEditError(`JSON 解析失败: ${e instanceof Error ? e.message : 'invalid JSON'}`);
    }
  };

  return (
    <div
      className="mt-1.5 ml-1 rounded border border-amber-500/30 bg-amber-500/5 p-2"
      data-testid="agent-node-approval-card"
      data-card-status={card.status}
    >
      <div className="flex items-start gap-1.5 text-[10.5px] text-amber-300 mb-1">
        <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
        <span className="font-semibold">
          HITL · {isResolved ? (card.status === 'approved' ? '已允许' : '已拒绝') : '待审批'}
        </span>
        <span className="text-fg2 ml-auto" data-testid="agent-node-approval-time">
          {formatRelative(card.createdAt)}
        </span>
      </div>
      <div className="text-[10.5px] text-fg1 mb-1.5 break-words">{card.reason}</div>
      {card.toolArgs && Object.keys(card.toolArgs).length > 0 && !editing && (
        <pre
          className="font-mono text-[10px] text-fg1 bg-[var(--code-bg)] rounded p-1.5 overflow-x-auto mb-1.5"
          data-testid="agent-node-approval-args"
        >
          {JSON.stringify(card.toolArgs, null, 2)}
        </pre>
      )}
      {editing && (
        <div className="mb-1.5" data-testid="agent-node-approval-edit-area">
          <textarea
            value={editedText}
            onChange={(e) => {
              setEditedText(e.target.value);
              setEditError(null);
            }}
            rows={Math.max(3, Math.min(8, editedText.split('\n').length + 1))}
            className="w-full font-mono text-[10px] text-fg1 bg-[var(--code-bg)] border border-amber-500/40 rounded p-1.5 outline-none focus:border-amber-500"
            spellCheck={false}
          />
          {editError && (
            <div className="text-[10px] text-red-500 mt-0.5">{editError}</div>
          )}
        </div>
      )}
      {!isResolved && (
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            disabled={busy}
            onClick={editing ? finishEdit : () => void handleApprove()}
            data-testid="agent-node-approval-approve"
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-semibold bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 border border-amber-500/40 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <ShieldCheck className="w-3 h-3" />
            )}
            {editing ? '用编辑后参数执行' : '允许执行'}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={handleReject}
            data-testid="agent-node-approval-reject"
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] font-semibold bg-red-500/10 hover:bg-red-500/20 text-red-300 border border-red-500/40 disabled:opacity-50"
          >
            {busy ? (
              <Loader2 className="w-3 h-3 animate-spin" />
            ) : (
              <ShieldX className="w-3 h-3" />
            )}
            拒绝
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => (editing ? setEditing(false) : startEdit())}
            data-testid="agent-node-approval-edit-toggle"
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10.5px] text-fg2 hover:text-fg1 border border-[var(--border)] disabled:opacity-50"
          >
            <Pencil className="w-3 h-3" />
            {editing ? '取消' : '编辑参数'}
          </button>
        </div>
      )}
    </div>
  );
}

// ============================================================
// 内部 helper：把后端 SSE 事件归一化为 store 入参（便于 ChatPage / runtime 调用）
// ============================================================

export interface IncomingAgentSwitch {
  type: 'agent_switch';
  agent: string;
  reason?: string;
  requestId?: string;
}

export interface IncomingAgentDone {
  type: 'agent_done';
  agent: string;
}

export type IncomingAgentEvent = IncomingAgentSwitch | IncomingAgentDone;

/**
 * 解析后端 SSE event payload 为 IncomingAgentEvent。
 * 容错：dataObj 缺字段 / type 不识别时返回 null，由调用方忽略。
 */
export function parseAgentEvent(dataObj: unknown): IncomingAgentEvent | null {
  if (!dataObj || typeof dataObj !== 'object') return null;
  const o = dataObj as Record<string, unknown>;
  const t = String(o.type ?? '');
  if (t === 'agent_switch') {
    const agent = String(o.agent ?? '');
    if (!agent) return null;
    return {
      type: 'agent_switch',
      agent,
      reason: typeof o.reason === 'string' ? o.reason : undefined,
      requestId: typeof o.request_id === 'string' ? o.request_id : undefined,
    };
  }
  if (t === 'agent_done') {
    return { type: 'agent_done', agent: String(o.agent ?? 'FINISH') };
  }
  return null;
}