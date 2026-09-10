/**
 * SessionSidebar — Session 管理侧栏（v2.1）
 *
 * 功能：
 * - 列出 chatStore.sessions 中所有 session（按 updatedAt 倒序）；
 * - 单击切换 activeSessionId；
 * - 新建 / 删除 / 重命名 session；
 * - 删除 session 时弹出 confirm 确认；
 * - "清空对话"：对当前 session 二级确认 + 调后端 /api/clear；
 *
 * 设计要点：
 * - 不引入新的 zustand store，直接消费 chatStore；
 * - 用 useUIStore 控制"侧栏开/合"（默认与全局 sidebar 同侧）；
 * - 用 ResizeObserver / window.resize 监听做 responsive（小屏自动收起）。
 */
import { useEffect, useMemo, useState, type FC } from 'react';
import {
  Plus,
  Trash2,
  MessageSquare,
  Pencil,
  Check,
  X,
  AlertTriangle,
  RotateCw,
  Loader2,
  Bot,
  Settings,
} from 'lucide-react';
import { useChatStore } from '@/stores/chatStore';
import { useUIStore } from '@/stores/uiStore';
import { useAgentStore } from '@/stores/agentStore';
import { api } from '@/lib/api';
import { cn, uid } from '@/lib/utils';
import { AgentConfigModal } from './AgentConfigModal';
import { WorkflowModeSelector } from './WorkflowModeSelector';

export const SessionSidebar: FC = () => {
  const sessions = useChatStore((s) => s.sessions);
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  const messagesBySession = useChatStore((s) => s.messages);
  const newSession = useChatStore((s) => s.newSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const renameSession = useChatStore((s) => s.renameSession);
  const setActive = useChatStore((s) => s.setActive);

  const sessionsCollapsed = useUIStore((s) => s.sessionsCollapsed);
  const toggleSessions = useUIStore((s) => s.toggleSessions);

  // v2.1 — Agent 切换
  const agentPresets = useAgentStore((s) => s.presets);
  const defaultAgentId = useAgentStore((s) => s.defaultAgentId);
  const sessionAgentMap = useAgentStore((s) => s.sessionAgentMap);
  const bindAgentToSession = useAgentStore((s) => s.bindAgentToSession);
  const loadAgentPresets = useAgentStore((s) => s.loadPresets);
  const [agentModalOpen, setAgentModalOpen] = useState(false);

  const activeAgentId = sessionAgentMap[activeSessionId] ?? defaultAgentId;
  const activePreset = useMemo(
    () => agentPresets.find((p) => p.id === activeAgentId) ?? agentPresets[0],
    [agentPresets, activeAgentId],
  );

  // 首次挂载加载 presets
  useEffect(() => {
    if (agentPresets.length === 0) {
      void loadAgentPresets();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onSwitchAgent = (agentId: string) => {
    bindAgentToSession(activeSessionId, agentId);
  };

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const [confirm, setConfirm] = useState<
    | { kind: 'delete'; sid: string; title: string }
    | { kind: 'clear'; sid: string; title: string }
    | null
  >(null);
  const [busy, setBusy] = useState<'delete' | 'clear' | null>(null);

  // 排序：最近活跃在前
  const list = useMemo(() => {
    return Object.values(sessions).sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0));
  }, [sessions]);

  // 自动收起（小屏）
  useEffect(() => {
    const mql = window.matchMedia('(max-width: 1024px)');
    if (mql.matches && !sessionsCollapsed) {
      useUIStore.getState().setSessionsCollapsed(true);
    }
    // 仅首次执行
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const onNew = () => {
    newSession();
  };

  const onRenameStart = (sid: string, title: string) => {
    setEditingId(sid);
    setEditingTitle(title);
  };
  const onRenameCommit = () => {
    if (editingId && editingTitle.trim()) {
      renameSession(editingId, editingTitle.trim().slice(0, 60));
    }
    setEditingId(null);
  };
  const onRenameCancel = () => {
    setEditingId(null);
  };

  const onDelete = async (sid: string) => {
    setBusy('delete');
    try {
      // 如果删的是当前 active，会触发自动创建新会话（store 已处理）
      deleteSession(sid);
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  };

  const onClear = async (sid: string) => {
    setBusy('clear');
    try {
      try {
        await api.clear();
      } catch {
        /* 后端失败不影响本地清空 */
      }
      // 清空该 session 的 messages（不动 session 元数据）
      useChatStore.setState((st) => ({
        messages: { ...st.messages, [sid]: [] },
      }));
    } finally {
      setBusy(null);
      setConfirm(null);
    }
  };

  if (sessionsCollapsed) {
    return (
      <div className="h-full flex flex-col items-center pt-3 border-r border-[var(--border)] bg-[var(--bg-1)] w-[56px]">
        <button
          type="button"
          onClick={toggleSessions}
          className="w-9 h-9 rounded-md flex items-center justify-center text-fg1 hover:text-fg0 hover-overlay"
          aria-label="展开 Session 列表"
          title="展开 Session 列表"
        >
          <MessageSquare className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={onNew}
          className="mt-2 w-9 h-9 rounded-md flex items-center justify-center bg-accent-grad text-white hover:brightness-110 shadow-glow"
          aria-label="新建 Session"
          title="新建 Session"
        >
          <Plus className="w-4 h-4" strokeWidth={2.4} />
        </button>
      </div>
    );
  }

  return (
    <div
      data-testid="session-sidebar"
      className="h-full flex flex-col border-r border-[var(--border)] bg-[var(--bg-1)] w-[260px] shrink-0"
    >
      {/* Header */}
      <div className="px-3 py-3 border-b border-[var(--border)] flex items-center gap-2">
        <MessageSquare className="w-4 h-4 text-accent1 shrink-0" />
        <h3 className="text-[12.5px] font-semibold text-fg0 flex-1 truncate">Session 列表</h3>
        <button
          type="button"
          onClick={onNew}
          className="w-7 h-7 rounded-md flex items-center justify-center text-fg1 hover:text-fg0 hover-overlay"
          aria-label="新建 Session"
          title="新建 Session"
        >
          <Plus className="w-3.5 h-3.5" />
        </button>
        <button
          type="button"
          onClick={toggleSessions}
          className="w-7 h-7 rounded-md flex items-center justify-center text-fg1 hover:text-fg0 hover-overlay"
          aria-label="收起 Session 列表"
          title="收起"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Workflow Mode Selector — 取代旧版「当前 AGENT」下拉 */}
      <div className="px-3 py-2 border-b border-[var(--border)] bg-[var(--bg-0)]/30">
        <WorkflowModeSelector />
        {/* 保留 Agent 预设入口（隐藏在 Workflow Mode 之下，作为详细配置） */}
        <div className="mt-1.5 flex items-center gap-1">
          <Bot className="w-3 h-3 text-fg2 shrink-0" />
          <span className="text-[10px] uppercase tracking-wider text-fg2 font-medium">
            详细 Agent 预设
          </span>
          <button
            type="button"
            data-testid="open-agent-config"
            onClick={() => setAgentModalOpen(true)}
            className="ml-auto w-5 h-5 rounded flex items-center justify-center text-fg2 hover:text-fg0 hover-overlay"
            aria-label="管理 Agent 预设"
            title="管理 Agent 预设"
          >
            <Settings className="w-3 h-3" />
          </button>
        </div>
        <select
          data-testid="agent-switcher"
          value={activeAgentId}
          onChange={(e) => onSwitchAgent(e.target.value)}
          className="w-full h-7 mt-1 px-2 bg-[var(--bg-0)] border border-[var(--border)] rounded text-[11.5px] text-fg0 outline-none focus:border-cyan-500/50"
        >
          {agentPresets.length === 0 ? (
            <option value={activeAgentId}>加载中…</option>
          ) : (
            agentPresets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.avatar} {p.name}
                {p.builtin ? ' (内置)' : ''}
              </option>
            ))
          )}
        </select>
        {activePreset && (
          <div className="mt-1 text-[10px] text-fg2 truncate" title={activePreset.description}>
            {activePreset.description || '暂无说明'}
          </div>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto py-1.5">
        {list.length === 0 ? (
          <p className="text-[11px] text-fg2 text-center px-3 py-4">暂无 Session</p>
        ) : (
          list.map((s) => {
            const isActive = s.id === activeSessionId;
            const isEditing = editingId === s.id;
            const msgCount = (messagesBySession[s.id] ?? []).length;
            return (
              <div
                key={s.id}
                data-testid="session-row"
                data-active={isActive ? 'true' : 'false'}
                className={cn(
                  'group/sess mx-1.5 my-0.5 rounded-md border transition-colors',
                  isActive
                    ? 'border-cyan-500/30 bg-cyan-500/5'
                    : 'border-transparent hover:border-[var(--border)] hover:bg-[var(--bg-2)]',
                )}
              >
                <div className="flex items-center gap-1.5 px-2 py-1.5">
                  {isEditing ? (
                    <>
                      <input
                        autoFocus
                        value={editingTitle}
                        onChange={(e) => setEditingTitle(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') onRenameCommit();
                          else if (e.key === 'Escape') onRenameCancel();
                        }}
                        className="flex-1 min-w-0 h-7 px-1.5 text-[12px] bg-[var(--bg-0)] border border-[var(--border)] rounded text-fg0 outline-none focus:border-cyan-500/50"
                        maxLength={60}
                        aria-label="重命名 Session"
                      />
                      <button
                        type="button"
                        onClick={onRenameCommit}
                        className="w-6 h-6 flex items-center justify-center text-emerald-400 hover:bg-emerald-500/10 rounded"
                        title="保存"
                      >
                        <Check className="w-3.5 h-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={onRenameCancel}
                        className="w-6 h-6 flex items-center justify-center text-fg2 hover:bg-[var(--bg-2)] rounded"
                        title="取消"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => setActive(s.id)}
                        className="flex-1 min-w-0 text-left truncate text-[12px]"
                        title={`${s.title}（${msgCount} 条消息）`}
                      >
                        <span
                          className={cn(
                            'truncate block',
                            isActive ? 'text-cyan-300 font-medium' : 'text-fg0',
                          )}
                        >
                          {s.title || '(未命名)'}
                        </span>
                        <span className="text-[10px] text-fg2 font-mono">
                          {msgCount > 0 ? `${msgCount} 条消息 · ` : ''}
                          {s.id.slice(0, 6)}
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={() => onRenameStart(s.id, s.title)}
                        className="w-6 h-6 flex items-center justify-center text-fg2 hover:text-fg0 hover:bg-[var(--bg-2)] rounded opacity-0 group-hover/sess:opacity-100"
                        title="重命名"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setConfirm({ kind: 'delete', sid: s.id, title: s.title })
                        }
                        className="w-6 h-6 flex items-center justify-center text-fg2 hover:text-rose-400 hover:bg-rose-500/10 rounded opacity-0 group-hover/sess:opacity-100"
                        title="删除 Session"
                      >
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer: 清空当前 Session 对话 */}
      <div className="px-2.5 py-2.5 border-t border-[var(--border)]">
        <button
          type="button"
          data-testid="clear-conversation-btn"
          onClick={() => {
            const cur = sessions[activeSessionId];
            setConfirm({ kind: 'clear', sid: activeSessionId, title: cur?.title ?? '(未命名)' });
          }}
          disabled={busy !== null}
          className="w-full h-8 px-2.5 text-[11.5px] rounded-md border border-amber-500/30 text-amber-300 hover:bg-amber-500/10 flex items-center justify-center gap-1.5 disabled:opacity-50"
          title="清空当前 Session 的对话与 Checkpointer"
        >
          {busy === 'clear' ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
          ) : (
            <RotateCw className="w-3.5 h-3.5" />
          )}
          清空当前对话
        </button>
      </div>

      {/* Confirm dialog */}
      {confirm && (
        <ConfirmDialog
          kind={confirm.kind}
          title={confirm.title}
          busy={busy !== null}
          onCancel={() => setConfirm(null)}
          onConfirm={async () => {
            if (confirm.kind === 'delete') await onDelete(confirm.sid);
            else await onClear(confirm.sid);
          }}
        />
      )}

      {/* Agent Config Modal（v2.1） */}
      {agentModalOpen && (
        <AgentConfigModal
          onClose={() => setAgentModalOpen(false)}
          initialPresetId={activeAgentId}
          onChanged={() => {
            // store 内部已更新；这里无需做额外动作
          }}
        />
      )}
    </div>
  );
};

// ============================================================
// Confirm Dialog（行内浮层，不依赖外部 modal）
// ============================================================
interface ConfirmDialogProps {
  kind: 'delete' | 'clear';
  title: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void> | void;
}

const ConfirmDialog: FC<ConfirmDialogProps> = ({ kind, title, busy, onCancel, onConfirm }) => {
  const isDelete = kind === 'delete';
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={isDelete ? '确认删除 Session' : '确认清空对话'}
      data-testid="confirm-dialog"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm px-4"
      onClick={onCancel}
    >
      <div
        className="max-w-sm w-full bg-[var(--bg-1)] border border-[var(--border)] rounded-lg shadow-2xl p-5 space-y-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-2.5">
          <AlertTriangle
            className={cn(
              'w-5 h-5 shrink-0 mt-0.5',
              isDelete ? 'text-rose-400' : 'text-amber-400',
            )}
          />
          <div className="flex-1 min-w-0">
            <h4 className="text-[14px] font-semibold text-fg0">
              {isDelete ? '删除 Session' : '清空对话'}
            </h4>
            <p className="text-[12px] text-fg1 mt-1.5 leading-relaxed">
              {isDelete ? (
                <>
                  确定要删除 Session <strong className="text-fg0">「{title}」</strong> 吗？
                  该操作不可恢复，历史消息将被永久移除。
                </>
              ) : (
                <>
                  确定要清空 Session <strong className="text-fg0">「{title}」</strong> 的对话吗？
                  会同时调用后端 <code className="font-mono">/api/clear</code> 清空 LangGraph Checkpointer。
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="h-8 px-3 text-[12px] rounded-md border border-[var(--border)] text-fg1 hover:text-fg0 hover-overlay disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            data-testid="confirm-yes"
            className={cn(
              'h-8 px-3 text-[12px] rounded-md font-medium flex items-center gap-1.5 disabled:opacity-50',
              isDelete
                ? 'bg-rose-500/20 text-rose-200 border border-rose-500/40 hover:bg-rose-500/30'
                : 'bg-amber-500/20 text-amber-200 border border-amber-500/40 hover:bg-amber-500/30',
            )}
          >
            {busy && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
            {isDelete ? '删除' : '清空'}
          </button>
        </div>
      </div>
    </div>
  );
};

// 兜底：在 module-level 暴露 uid 给测试 mock（避免循环引用）
export const _testHelpers = { uid };
