/**
 * v2.1 slim — ChatPage
 *
 * 使用 useAgentLocalRuntime + history adapter（持久化到 zustand → localStorage）。
 * 切换会话时用 key={activeSessionId} 让整个 runtime 子树重建。
 */
import { AssistantRuntimeProvider } from '@assistant-ui/react';
import { Thread } from '@/components/assistant-ui/thread';
import { ToolCallTimeline } from '@/components/v2/ToolCallTimeline';
import { AttachmentUploader } from '@/components/v2/AttachmentUploader';
import { ModelChip } from '@/components/chat/ModelChip';
import { useAgentLocalRuntime } from '@/hooks/useAgentLocalRuntime';
import { useChatStore } from '@/stores/chatStore';

export function ChatPage() {
  const runtime = useAgentLocalRuntime();
  const activeSessionId = useChatStore((s) => s.activeSessionId);
  return (
    // 关键：key 让切会话时整个 runtime 子树（包括 Timeline）重建，重新 load 新 session 历史
    <AssistantRuntimeProvider key={activeSessionId} runtime={runtime}>
      <div className="flex h-full flex-col">
        {/* 顶部 model chip：与 Tools 页「当前激活」数据同源（/api/models） */}
        <div className="h-12 flex items-center justify-between px-4 border-b border-[var(--border)] shrink-0">
          <ModelChip />
          <div className="text-[11px] text-fg2">
            点击切换 · Tools 页 /admin?tab=tools
          </div>
        </div>
        <div className="flex flex-1 min-h-0">
          <div className="flex-1 min-w-0">
            <Thread />
          </div>
          <aside className="w-80 border-l border-slate-200 dark:border-slate-800 p-4 hidden lg:block overflow-y-auto">
            <h2 className="text-sm font-semibold mb-2">工具调用时间线</h2>
            <ToolCallTimeline />
            <h2 className="text-sm font-semibold mt-6 mb-2">附件</h2>
            <AttachmentUploader />
          </aside>
        </div>
      </div>
    </AssistantRuntimeProvider>
  );
}
