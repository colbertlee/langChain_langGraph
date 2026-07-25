import { type FC, useState } from 'react';
import { useAui, useAuiState } from '@assistant-ui/react';
import { Plus, MessageSquare, Pencil, Trash2, Check, X } from 'lucide-react';
import { useChatStore } from '@/stores/chatStore';
import { cn, formatRelative } from '@/lib/utils';

interface ThreadRowData {
  remoteId: string;
  title: string;
}

const ThreadListItem: FC<{ data: ThreadRowData }> = ({ data }) => {
  const activeId = useChatStore((s) => s.activeSessionId);
  const setActive = useChatStore((s) => s.setActive);
  const newSession = useChatStore((s) => s.newSession);
  const deleteSession = useChatStore((s) => s.deleteSession);
  const renameSession = useChatStore((s) => s.renameSession);
  const aui = useAui();
  const sess = useChatStore((s) => s.sessions[data.remoteId]);
  const msgCount = useChatStore((s) => (s.messages[data.remoteId] ?? []).length);

  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState('');

  const isActive = data.remoteId === activeId;
  const title = data.title || sess?.title || '新会话';

  return (
    <div
      onClick={() => {
        if (data.remoteId) {
          setActive(data.remoteId);
          aui.threads().switchToThread(data.remoteId);
        }
      }}
      className={cn(
        'group relative rounded-[10px] transition-colors cursor-pointer',
        isActive
          ? 'bg-gradient-to-r from-cyan-500/10 to-blue-500/5 ring-1 ring-cyan-500/30'
          : 'hover:bg-white/[0.04]',
      )}
    >
      <div className="flex items-center gap-2 px-3 py-2.5">
        <MessageSquare
          className={cn(
            'w-3.5 h-3.5 shrink-0',
            isActive ? 'text-accent1' : 'text-fg2',
          )}
        />
        <div className="flex-1 min-w-0">
          {editing ? (
            <div className="flex items-center gap-1">
              <input
                autoFocus
                value={val}
                onChange={(e) => setVal(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                className="flex-1 bg-transparent text-[13px] text-fg0 outline-none border-b border-accent1"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    if (val.trim()) renameSession(data.remoteId, val.trim());
                    setEditing(false);
                  }
                  if (e.key === 'Escape') setEditing(false);
                }}
              />
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (val.trim()) renameSession(data.remoteId, val.trim());
                  setEditing(false);
                }}
                className="p-0.5 text-success"
              >
                <Check className="w-3 h-3" />
              </button>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setEditing(false);
                }}
                className="p-0.5 text-fg2"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ) : (
            <>
              <div className="text-[13px] text-fg0 truncate font-medium">{title}</div>
              <div className="text-[10.5px] text-fg2 flex items-center gap-1.5">
                <span>{formatRelative(sess?.updatedAt ?? Date.now())}</span>
                {msgCount > 0 && (
                  <>
                    <span>·</span>
                    <span>{msgCount} 条</span>
                  </>
                )}
              </div>
            </>
          )}
        </div>
      </div>
      {!editing && (
        <div className="absolute right-1.5 top-1/2 -translate-y-1/2 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setEditing(true);
              setVal(title);
            }}
            className="p-1 rounded-md hover:bg-white/10 text-fg2 hover:text-fg0"
            title="重命名"
          >
            <Pencil className="w-3 h-3" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              if (confirm('删除该会话？')) {
                if (isActive) newSession();
                deleteSession(data.remoteId);
              }
            }}
            className="p-1 rounded-md hover:bg-white/10 text-fg2 hover:text-danger"
            title="删除"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      )}
    </div>
  );
};

export const SessionList: FC = () => {
  const aui = useAui();
  const sessions = useChatStore((s) => s.sessions);
  const list: ThreadRowData[] = Object.values(sessions)
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .map((x) => ({ remoteId: x.id, title: x.title }));

  return (
    <aside className="w-64 shrink-0 border-r border-[var(--border)] flex flex-col bg-[rgba(10,10,11,0.4)]">
      <div className="p-3 border-b border-[var(--border)]">
        <button
          onClick={() => {
            useChatStore.getState().newSession();
            aui.threads().switchToNewThread();
          }}
          className="btn-primary w-full h-9 text-[13px]"
        >
          <Plus className="w-4 h-4" strokeWidth={2.2} />
          新建会话
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-2 space-y-0.5 stagger">
        {list.map((row) => (
          <ThreadListItem key={row.remoteId} data={row} />
        ))}
        {list.length === 0 && (
          <div className="text-center text-fg2 text-[12px] py-8">暂无会话</div>
        )}
      </div>
    </aside>
  );
};

// 防止未使用
void useAuiState;
