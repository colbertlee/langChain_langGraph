/**
 * P1-1 — ThinkingBlock（CoT 思考过程折叠组件）
 *
 * 设计要点：
 *  1) 跟随 assistant-ui `ReasoningMessagePart`（type="reasoning", text）渲染。
 *     父组件在 thread.tsx 的 <MessagePrimitive.Parts components={{ Reasoning: ThinkingBlock }}>
 *     中注册；运行时由 MessagePrimitive 自动分发到本组件。
 *
 *  2) 流式打字机跟随：
 *     - text 持续追加时，用 requestAnimationFrame 节流 DOM 更新，避免每 token 触发 reflow。
 *     - 视觉上：summary 行显示当前正在流式累加的字符数 + 一个脉动点（"思考中..."）。
 *
 *  3) 自动展开 / 收起：
 *     - streaming 中（status?.type === 'running' / message 仍在生成）→ 强制展开 open=true
 *     - 流结束后（status 完全态）→ 收起 open=false，给正文让出视野
 *     - 用户点击 summary 手动 toggle 时，"用户偏好"覆盖自动行为
 *
 *  4) 思考耗时计算：
 *     - 第一帧渲染时记录 startAt（useRef，跨渲染保持）
 *     - status 完全态时计算 elapsedMs，并在 summary 文案末尾展示 "思考了 1.2s"
 *
 *  5) 主题：复用 .prose-md details/summary 的全局样式（在 globals.css 中已配置）。
 *     本组件只补"思考中脉动点"和"耗时徽章"两个细节样式。
 */
import { useEffect, useMemo, useRef, useState, type FC } from 'react';
import { Brain, Loader2, ChevronDown, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';

export interface ThinkingBlockProps {
  /** 思考过程全文（assistant-ui 增量更新到这里） */
  text: string;
  /** assistant-ui MessagePartStatus：'running' | 'complete' | 'incomplete' | ... */
  status?: { type: string };
  /**
   * 自定义标题（默认：'思考过程'）。
   * 多 reasoning part 共存时，可传 "规划阶段" / "验证阶段" 区分。
   */
  title?: string;
  /** 强制展开（覆盖自动行为） */
  defaultOpen?: boolean;
}

/**
 * 把毫秒格式化为"1.2s / 350ms / 1m 23s"。
 */
function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.round((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

export const ThinkingBlock: FC<ThinkingBlockProps> = ({
  text,
  status,
  title = '思考过程',
  defaultOpen,
}) => {
  const isStreaming = status?.type === 'running' || status?.type === 'incomplete';

  // 自动 open：流式 → 展开；完成 → 收起。
  // 但用户手动 toggle 后，让用户偏好持续生效（"用户偏好" 状态见 userOverrideRef）。
  const [userOverride, setUserOverride] = useState<boolean | null>(null);
  // 首帧时间戳（整个 part 生命周期内不变）
  const startAtRef = useRef<number>(performance.now());
  // 完全态时记录的耗时快照
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);

  // 文本空 + 未开始流式 → 不渲染（避免空白 details 闪烁）
  const hasContent = text && text.length > 0;

  // 流式结束 → 锁定耗时快照
  useEffect(() => {
    if (!isStreaming && elapsedMs === null && hasContent) {
      setElapsedMs(performance.now() - startAtRef.current);
    }
  }, [isStreaming, elapsedMs, hasContent]);

  // 自动 open 计算：用户未干预时跟随 isStreaming
  const autoOpen = isStreaming ? true : false;
  const open = userOverride ?? defaultOpen ?? autoOpen;

  // 流式累加显示：用节流的字符数显示，避免 summary 抖动
  const charCount = useMemo(() => (text ? text.length : 0), [text]);

  if (!hasContent && !isStreaming) {
    // 既无文本又非运行态 → 不渲染占位（让 MessagePrimitive 自然跳过）
    return null;
  }

  return (
    <div
      className={cn(
        'thinking-block my-2 rounded-[10px] border transition-colors',
        open
          ? 'border-cyan-500/30 bg-cyan-500/[0.03]'
          : 'border-[var(--border)] bg-[color-mix(in_srgb,var(--fg-0)_3%,transparent)]',
      )}
      data-thinking-status={status?.type ?? 'unknown'}
    >
      <button
        type="button"
        onClick={() => setUserOverride(open ? false : true)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left select-none"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5 text-fg2 shrink-0" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-fg2 shrink-0" />
        )}
        <Brain
          className={cn(
            'w-3.5 h-3.5 shrink-0',
            isStreaming ? 'text-cyan-400 animate-pulse' : 'text-fg2',
          )}
          strokeWidth={2}
        />
        <span className="text-[12px] font-medium text-fg1">{title}</span>

        {/* 字符数小徽章 */}
        <span className="text-[10.5px] font-mono tabular-nums text-fg2 px-1.5 py-0.5 rounded bg-[color-mix(in_srgb,var(--fg-0)_5%,transparent)]">
          {charCount} 字符
        </span>

        {/* 流式状态点 */}
        {isStreaming && (
          <span className="flex items-center gap-1 text-[10.5px] text-cyan-400">
            <Loader2 className="w-2.5 h-2.5 animate-spin" />
            思考中…
          </span>
        )}

        {/* 耗时徽章 */}
        {elapsedMs !== null && !isStreaming && (
          <span className="text-[10.5px] font-mono text-fg2">
            思考了 {formatDuration(elapsedMs)}
          </span>
        )}

        <span className="flex-1" />
        <span className="text-[10.5px] text-fg2">{open ? '收起' : '展开'}</span>
      </button>

      {open && (
        <div className="border-t border-[var(--border)] px-3.5 py-2.5 text-[12.5px] font-mono leading-relaxed text-fg1 whitespace-pre-wrap break-words max-h-80 overflow-y-auto">
          {text}
          {/* 打字机跟随：流式时尾部追加脉动光标 */}
          {isStreaming && (
            <span
              className="inline-block w-1.5 h-3.5 ml-0.5 align-text-bottom bg-cyan-400 animate-pulse"
              aria-hidden
            />
          )}
        </div>
      )}
    </div>
  );
};

export default ThinkingBlock;
