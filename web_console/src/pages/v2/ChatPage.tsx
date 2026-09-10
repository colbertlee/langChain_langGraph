/**
 * v2.1 slim — ChatPage
 *
 * 使用 useAgentLocalRuntime + history adapter（持久化到 zustand → localStorage）。
 * 切换会话时用 key={activeSessionId} 让整个 runtime 子树重建。
 *
 * v2.2.1 — 在侧栏加入 HITL 审批面板（ApprovalCard）。
 * v2.2.3 — 在侧栏加入 Agent 协作过程（AgentExecutionGraph）。
 */
import { useMemo, useRef, useEffect } from 'react';
import { AssistantRuntimeProvider } from '@assistant-ui/react';
import { Thread } from '@/components/assistant-ui/thread';
import { ToolCallTimeline } from '@/components/v2/ToolCallTimeline';
import { AttachmentUploader } from '@/components/v2/AttachmentUploader';
import { ApprovalCard } from '@/components/v2/ApprovalCard';
import { AgentExecutionGraph } from '@/components/v2/AgentExecutionGraph';
import { ResumeDrawer } from '@/components/v2/ResumeDrawer';
import { ModelChip } from '@/components/chat/ModelChip';
import { useAgentLocalRuntime } from '@/hooks/useAgentLocalRuntime';
import { useChatStore } from '@/stores/chatStore';
import { ShieldAlert, GitBranch } from 'lucide-react';

export function ChatPage() {
  const runtime = useAgentLocalRuntime();
  const activeSessionId = useChatStore((s) => s.activeSessionId);

  // 修复 React `Maximum update depth exceeded` 死循环：
  // zustand persist 在 mount 阶段会异步 hydrate，可能在 Provider mount 完成前
  // 再次写入 activeSessionId / 其他字段，导致 key 重算 → Provider 重建 →
  // runtime 重建 → load / append 又触发 store 写入 → 死循环。
  //
  // 用 ref 锁定首次拿到的 sessionId，只在它真正"切换"时才更新，
  // 避免 mount 期间的中间态导致 Provider 反复重建。
  const lockedSessionIdRef = useRef<string>(activeSessionId);
  const lastSeenSessionIdRef = useRef<string>(activeSessionId);
  if (activeSessionId !== lastSeenSessionIdRef.current) {
    lastSeenSessionIdRef.current = activeSessionId;
    lockedSessionIdRef.current = activeSessionId;
  }
  const sessionKey = useMemo(
    () => lockedSessionIdRef.current,
    [lockedSessionIdRef.current],
  );

  return (
    // 关键：key 让切会话时整个 runtime 子树（包括 Timeline）重建，重新 load 新 session 历史
    <AssistantRuntimeProvider key={sessionKey} runtime={runtime}>
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
          <aside className="w-80 border-l border-slate-200 dark:border-slate-800 p-4 hidden lg:block overflow-y-auto space-y-4">
            {/* v2.2.3 — Multi-Agent Supervisor 协作过程 */}
            <div>
              <h2 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
                <GitBranch className="w-3.5 h-3.5 text-accent1" />
                Agent 协作过程
              </h2>
              <AgentExecutionGraph sessionId={activeSessionId} defaultExpanded />
            </div>
            {/* v2.2.1 — HITL 待审批卡片（高风险工具拦截） */}
            <div>
              <h2 className="text-sm font-semibold mb-2 flex items-center gap-1.5">
                <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
                高风险工具审批
              </h2>
              <ApprovalCard sessionId={activeSessionId} />
            </div>
            <div>
              <h2 className="text-sm font-semibold mb-2">工具调用时间线</h2>
              <ToolCallTimeline />
            </div>
            <div>
              <h2 className="text-sm font-semibold mb-2">附件</h2>
              <AttachmentUploader />
            </div>
          </aside>
        </div>
        {/* P1-5 — HITL 拒绝/批准后 resume 累积文本（右下角浮动） */}
        <ResumeDrawer sessionId={activeSessionId} />
      </div>
    </AssistantRuntimeProvider>
  );
}
