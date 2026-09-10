/**
 * P1-5 — ResumeDrawer
 *
 * 显示当前 session 的 HITL resume 累积文本（来自 chatStore.resumeBySession）。
 * 用户点击 reject/approve 后，ApprovalCard 会自动订阅 resume_url SSE 流，
 * 续生成的内容累积到这里（独立于主 messages，避免污染 assistant-ui 的 messages）。
 *
 * 行为：
 *  - 浮动在右下角（fixed bottom-4 right-4）
 *  - 仅当 resumeBySession[activeSessionId] 非空时显示
 *  - 提供「关闭」按钮：调用 chatStore.clearResumeText 清空
 *  - 内容用 MarkdownText-like 渲染（这里简化：直接 prose-md 样式）
 */
import { useEffect, useState } from 'react';
import { X, ChevronDown, ChevronUp, Activity } from 'lucide-react';
import { useChatStore } from '@/stores/chatStore';

export interface ResumeDrawerProps {
  /** 当前 session id（可选；不传则从 useChatStore 读 activeSessionId） */
  sessionId?: string;
}

export function ResumeDrawer({ sessionId: sessionIdProp }: ResumeDrawerProps) {
  const activeId = useChatStore((s) => s.activeSessionId);
  const sid = sessionIdProp ?? activeId;
  const text = useChatStore((s) => s.resumeBySession[sid] ?? '');
  const clearResumeText = useChatStore((s) => s.clearResumeText);
  const [collapsed, setCollapsed] = useState(false);

  // 新内容到达时自动展开 + 滚到底
  useEffect(() => {
    if (text.length > 0) setCollapsed(false);
  }, [text.length]);

  if (!text) return null;

  return (
    <div
      className="fixed bottom-4 right-4 z-50 w-[min(420px,calc(100vw-2rem))] max-h-[60vh] rounded-[12px] border border-[var(--border)] bg-[var(--bg-1)] shadow-glass overflow-hidden flex flex-col"
      data-testid="resume-drawer"
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--fg-0)_4%,transparent)]">
        <Activity className="w-3.5 h-3.5 text-cyan-400" />
        <span className="text-[12px] font-semibold text-fg1 flex-1">
          模型续生成
        </span>
        <span className="text-[10.5px] font-mono text-fg2">
          {text.length} 字符
        </span>
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="p-1 rounded hover-overlay text-fg2 hover:text-fg0"
          aria-label={collapsed ? '展开' : '收起'}
          type="button"
        >
          {collapsed ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
        </button>
        <button
          onClick={() => clearResumeText(sid)}
          className="p-1 rounded hover-overlay text-fg2 hover:text-fg0"
          aria-label="关闭"
          type="button"
          data-testid="resume-drawer-close"
        >
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      {!collapsed && (
        <div
          className="flex-1 overflow-y-auto px-3 py-2 text-[12.5px] leading-relaxed text-fg1 prose-md whitespace-pre-wrap break-words"
          data-testid="resume-drawer-content"
        >
          {text}
        </div>
      )}
    </div>
  );
}

export default ResumeDrawer;
