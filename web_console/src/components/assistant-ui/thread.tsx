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
import { ThinkingBlock } from './ThinkingBlock';

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
  // 围绕该 Agent 的真实能力设计示例：
  // ① 复杂任务规划与多步推理
  // ② 代码理解、生成、修改与 review
  // ③ 项目文件 / 数据 / Git 操作
  // 不放"天气/计算/搜索"等单轮问答式例子（这些 LLM 直接答，不必走 Agent）。
  const examples = [
    {
      icon: '🧠',
      t: '帮我设计一个支持多步工具调用的 agent 架构，并对比 LangGraph 与 CrewAI 的取舍',
    },
    {
      icon: '💻',
      t: '阅读 ./ai_agent/app.py，画出从 /api/chat 到 LangGraph invoke 的完整调用链',
    },
    {
      icon: '🔧',
      t: '在 ai_agent/tools_v2.py 里加一个新工具 subcommand=pdf，按规范实现并接入 agent',
    },
    {
      icon: '📊',
      t: '基于本仓库最近的 commits 写一份 CHANGELOG，重点列出 v2_slim 的 API 变更',
    },
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
          <div className="mb-1.5 flex items-center gap-1.5 px-2 py-1 rounded-md bg-[color-mix(in_srgb,var(--fg-0)_5%,transparent)] border border-[var(--border)] text-[11px] text-fg1 w-fit">
            <Layers className="w-3 h-3 text-accent1" />
            <span>分支</span>
            <div className="flex items-center gap-0.5">
              <button
                onClick={() => aui.message().switchToBranch({ position: 'previous' })}
                className="p-0.5 rounded hover-overlay-strong text-fg2 hover:text-fg0"
                aria-label="上一分支"
              >
                <ChevronLeft className="w-3 h-3" />
              </button>
              <span className="font-mono tabular-nums text-[10.5px] px-1">
                {branchNumber} / {branchCount}
              </span>
              <button
                onClick={() => aui.message().switchToBranch({ position: 'next' })}
                className="p-0.5 rounded hover-overlay-strong text-fg2 hover:text-fg0"
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
              // assistant-ui 0.14 标准 StandardComponents 类型只含 Text/Image/InProgress/Messages，
              // ToolFallback / Reasoning 是运行时识别的扩展 slot，需断言成 any 绕过。
              components={
                {
                  Text: MarkdownText,
                  ToolFallback: ToolCallCard,
                  Reasoning: ThinkingBlock,
                } as any
              }
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
        className="text-fg2 hover:text-fg0 text-[11px] flex items-center gap-1 px-1.5 py-0.5 rounded hover-overlay"
        title="复制"
      >
        <Copy className="w-3 h-3" />
        复制
      </button>
      {showMeta && (
        <>
          <button
            onClick={() => aui.message().reload()}
            className="text-fg2 hover:text-fg0 text-[11px] flex items-center gap-1 px-1.5 py-0.5 rounded hover-overlay"
            title="重新生成"
          >
            <RotateCw className="w-3 h-3" />
            重新生成
          </button>
          <button
            onClick={edit}
            className="text-fg2 hover:text-fg0 text-[11px] flex items-center gap-1 px-1.5 py-0.5 rounded hover-overlay"
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
      <div className="relative group flex items-center gap-2 pl-2 pr-1 py-1 rounded-md border border-[var(--border)] bg-[color-mix(in_srgb,var(--fg-0)_5%,transparent)]">
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
          className="w-5 h-5 rounded flex items-center justify-center text-fg2 hover:text-fg0 hover-overlay-strong"
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
    <ComposerPrimitive.Root className="border-t border-[var(--border)] p-4" style={{ backgroundColor: 'var(--bg-1)' }}>
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
                className="w-7 h-7 rounded-md flex items-center justify-center text-fg2 hover:text-fg0 hover-overlay transition-colors"
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
