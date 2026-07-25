import { type FC } from 'react';
import {
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  useAui,
  useAuiState,
} from '@assistant-ui/react';
import { Send, Square, Bot, User as UserIcon, Copy, RotateCw, Pencil, ChevronLeft, ChevronRight, Paperclip, X, Layers } from 'lucide-react';
import { MarkdownText } from './markdown-text';
import { ToolCallCard } from './tool-fallback';

export const Thread: FC = () => {
  return (
    <ThreadPrimitive.Root className="flex flex-col h-full">
      <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto px-4 py-4">
        <ThreadPrimitive.Empty>
          <EmptyState />
        </ThreadPrimitive.Empty>
        <ThreadPrimitive.Messages
          components={{
            UserMessage,
            AssistantMessage,
          }}
        />
      </ThreadPrimitive.Viewport>
      <Composer />
    </ThreadPrimitive.Root>
  );
};

const EmptyState: FC = () => {
  const examples = [
    { icon: '🔍', t: '搜索一下 LangGraph 最新版本' },
    { icon: '📂', t: '查看 ./ai_agent 目录结构' },
    { icon: '🧮', t: '计算 (1+2i)*(3-4i) 的复数乘法' },
    { icon: '📚', t: '在知识库里查找 "上下文持久化"' },
  ];
  return (
    <div className="h-full min-h-[60vh] flex flex-col items-center justify-center px-6 text-center">
      <div className="relative w-16 h-16 rounded-2xl bg-accent-grad flex items-center justify-center mb-5 shadow-glow">
        <Bot className="w-8 h-8 text-white" strokeWidth={2} />
        <div className="absolute inset-0 rounded-2xl bg-accent-grad blur-2xl opacity-40 -z-10" />
      </div>
      <h2 className="text-[22px] font-bold mb-1.5">
        <span className="grad-text">Agent Console</span>
      </h2>
      <p className="text-fg1 text-sm max-w-md mb-7">
        基于 assistant-ui + LangGraph 的多功能 Agent。流式对话、工具调用可视化、分支编辑、附件上传开箱即用。
      </p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 w-full max-w-2xl">
        {examples.map((e, i) => (
          <div
            key={i}
            className="text-left p-3.5 rounded-[12px] border border-[var(--border)] bg-[var(--bg-1)] hover:border-cyan-500/30 hover:bg-[var(--bg-2)] transition-colors cursor-pointer"
          >
            <div className="text-lg mb-1">{e.icon}</div>
            <div className="text-[13px] font-medium text-fg0">{e.t}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

const UserMessage: FC = () => {
  return (
    <MessagePrimitive.Root className="flex gap-3 py-4 justify-end animate-fade-in-up">
      <div className="min-w-0 max-w-3xl rounded-[12px] px-4 py-3 border bg-gradient-to-br from-cyan-500/10 to-blue-500/10 border-cyan-500/25">
        <div className="prose-md whitespace-pre-wrap">
          <MessagePrimitive.Parts />
        </div>
      </div>
      <div className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-[var(--bg-2)] border border-[var(--border)]">
        <UserIcon className="w-4 h-4 text-fg1" strokeWidth={2} />
      </div>
    </MessagePrimitive.Root>
  );
};

const AssistantMessage: FC = () => {
  const aui = useAui();
  const branchCount = useAuiState((s) => s.message.branchCount);
  const branchNumber = useAuiState((s) => s.message.branchNumber);
  const hasBranches = branchCount > 1;

  return (
    <MessagePrimitive.Root className="flex gap-3 py-4 animate-fade-in-up group">
      <div className="shrink-0 w-7 h-7 rounded-lg flex items-center justify-center bg-accent-grad shadow-glow">
        <Bot className="w-4 h-4 text-white" strokeWidth={2.2} />
      </div>
      <div className="min-w-0 max-w-3xl">
        {hasBranches && (
          <div className="mb-1.5 flex items-center gap-1.5 px-2 py-1 rounded-md bg-white/[0.04] border border-[var(--border)] text-[11px] text-fg1 w-fit">
            <Layers className="w-3 h-3 text-accent1" />
            <span>分支</span>
            <div className="flex items-center gap-0.5">
              <button
                onClick={() => aui.message().switchToBranch({ position: 'previous' })}
                className="p-0.5 rounded hover:bg-white/10 text-fg2 hover:text-fg0"
                aria-label="上一分支"
              >
                <ChevronLeft className="w-3 h-3" />
              </button>
              <span className="font-mono tabular-nums text-[10.5px] px-1">
                {branchNumber} / {branchCount}
              </span>
              <button
                onClick={() => aui.message().switchToBranch({ position: 'next' })}
                className="p-0.5 rounded hover:bg-white/10 text-fg2 hover:text-fg0"
                aria-label="下一分支"
              >
                <ChevronRight className="w-3 h-3" />
              </button>
            </div>
          </div>
        )}
        <div className="rounded-[12px] px-4 py-3 border bg-[var(--bg-1)] border-[var(--border)] shadow-glass">
          <div className="prose-md">
            <MessagePrimitive.Parts
              // @ts-expect-error assistant-ui 0.14 types miss ToolFallback
              components={{ Text: MarkdownText, ToolFallback: ToolCallCard }}
            />
          </div>
        </div>
        <AssistantActions />
      </div>
    </MessagePrimitive.Root>
  );
};

const AssistantActions: FC = () => {
  const aui = useAui();
  const statusType = useAuiState((s) => s.message.status?.type);
  const showMeta = statusType !== 'incomplete' && statusType !== 'requires-action';

  const copy = () => {
    const text = aui.message().getCopyText();
    navigator.clipboard.writeText(text).catch(() => {});
  };

  const edit = () => {
    aui.message().composer().setText(aui.message().getCopyText());
  };

  return (
    <div className="mt-1.5 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
      <button
        onClick={copy}
        className="text-fg2 hover:text-fg0 text-[11px] flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-white/5"
        title="复制"
      >
        <Copy className="w-3 h-3" />
        复制
      </button>
      {showMeta && (
        <>
          <button
            onClick={() => aui.message().reload()}
            className="text-fg2 hover:text-fg0 text-[11px] flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-white/5"
            title="重新生成"
          >
            <RotateCw className="w-3 h-3" />
            重新生成
          </button>
          <button
            onClick={edit}
            className="text-fg2 hover:text-fg0 text-[11px] flex items-center gap-1 px-1.5 py-0.5 rounded hover:bg-white/5"
            title="编辑"
          >
            <Pencil className="w-3 h-3" />
            编辑
          </button>
        </>
      )}
    </div>
  );
};

// ============================================================
// Composer
// ============================================================
interface AttachmentLike {
  id: string;
  name: string;
  type: string;
  content: Array<{ type: string; image?: string }>;
  remove?: () => Promise<void>;
}

const AttachmentPreview: FC<{ attachment: any }> = ({ attachment }) => {
  const img = attachment.content?.find((c: { type: string }) => c.type === 'image');
  return (
    <div className="flex flex-wrap gap-1.5 px-3 pt-2">
      <div className="relative group flex items-center gap-2 pl-2 pr-1 py-1 rounded-md border border-[var(--border)] bg-white/[0.04]">
        {img?.image ? (
          <img
            src={img.image}
            alt={attachment.name ?? '附件'}
            className="w-6 h-6 rounded object-cover"
          />
        ) : (
          <div className="w-6 h-6 rounded bg-[var(--bg-2)] flex items-center justify-center text-fg2">
            <Paperclip className="w-3 h-3" />
          </div>
        )}
        <span className="text-[11px] text-fg1 max-w-[120px] truncate">
          {attachment.name ?? '附件'}
        </span>
        <button
          onClick={() => void attachment.remove?.()}
          className="w-5 h-5 rounded flex items-center justify-center text-fg2 hover:text-fg0 hover:bg-white/10"
          aria-label="移除附件"
          type="button"
        >
          <X className="w-3 h-3" />
        </button>
      </div>
    </div>
  );
};
const Composer: FC = () => {
  return (
    <ComposerPrimitive.Root className="border-t border-[var(--border)] bg-[rgba(10,10,11,0.7)] backdrop-blur-xl p-4">
      <div className="max-w-3xl mx-auto">
        <div className="rounded-[14px] border border-[var(--border)] bg-[var(--bg-1)] focus-within:border-cyan-500/40 focus-within:shadow-glow transition-all">
          <ComposerPrimitive.Attachments>
            {({ attachment }) => <AttachmentPreview attachment={attachment} />}
          </ComposerPrimitive.Attachments>
          <ComposerPrimitive.Input
            placeholder="输入消息，回车发送…"
            className="w-full min-h-[48px] max-h-[220px] resize-none bg-transparent text-[14px] text-fg0 placeholder:text-fg2 outline-none px-4 py-3 focus:outline-none"
            rows={1}
          />
          <div className="flex items-center justify-between px-2 pb-1.5">
            <div className="flex items-center gap-1">
              <ComposerPrimitive.AddAttachment
                className="w-7 h-7 rounded-md flex items-center justify-center text-fg2 hover:text-fg0 hover:bg-white/5 transition-colors"
                aria-label="添加附件"
              >
                <Paperclip className="w-3.5 h-3.5" />
              </ComposerPrimitive.AddAttachment>
              <ComposerPrimitive.Send
                className="hidden"
                aria-hidden
              />
            </div>
            <ComposerAction />
          </div>
        </div>
        <div className="text-center mt-1.5">
          <span className="text-[10.5px] text-fg2 font-mono">
            Enter 发送 · Shift+Enter 换行 · assistant-ui 驱动
          </span>
        </div>
      </div>
    </ComposerPrimitive.Root>
  );
};

const ComposerAction: FC = () => {
  return (
    <div className="flex items-center gap-1">
      <ComposerPrimitive.Cancel
        className="hidden data-[running]:inline-flex w-9 h-9 rounded-[10px] items-center justify-center bg-[var(--danger)] text-white shadow-lg shadow-rose-500/30 hover:brightness-110 transition"
        aria-label="停止"
      >
        <Square className="w-3.5 h-3.5" fill="currentColor" />
      </ComposerPrimitive.Cancel>
      <ComposerPrimitive.Send
        className="w-9 h-9 rounded-[10px] flex items-center justify-center bg-accent-grad text-white shadow-glow hover:brightness-110 transition data-[disabled]:opacity-30 data-[disabled]:cursor-not-allowed"
        aria-label="发送"
      >
        <Send className="w-4 h-4" strokeWidth={2.2} />
      </ComposerPrimitive.Send>
    </div>
  );
};
