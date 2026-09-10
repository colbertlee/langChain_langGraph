/**
 * CodeBlock — 统一代码块组件（流式场景优化）
 *
 * 设计要点：
 * 1. 流式打字不闪烁：
 *    - SyntaxHighlighter 体积大、re-render 慢 → 用 React.memo + useDeferredValue 把
 *      "代码内容变化" 标记为低优先级更新，让 React 先完成 user input 的高频帧再渲染。
 *    - 用 stable `key={lang}` 让 React 在语言不变时复用同一棵子树，避免每帧重建。
 * 2. 一键复制：CopyButton（自动 fade 反馈"已复制 ✓"）
 * 3. 长代码块折叠：> 18 行默认折叠，点击展开/收起
 * 4. 横向滚动：max-w-full + overflow-x-auto + sticky language tag（视觉锚）
 */
import { memo, useDeferredValue, useMemo, useState, type FC } from 'react';
import { Check, ChevronDown, ChevronRight, Copy } from 'lucide-react';
// prism-light 是 default export，d.ts 没暴露路径；走 /dist 直接导入
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - prism-light 没有顶层 d.ts 声明
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism-light.js';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

import { isSupportedLang, SUPPORTED_LANGS } from '@/lib/syntaxLanguages';
import { cn } from '@/lib/utils';

// 通过 import 触发 side-effect 注册
// eslint-disable-next-line @typescript-eslint/no-unused-expressions
[SUPPORTED_LANGS];

interface CodeBlockProps {
  /** 编程语言（如 "python"、"typescript"）；未识别时按纯文本渲染 */
  lang: string | null;
  /** 原始代码内容（未做 escape 处理，本组件内部处理） */
  code: string;
  /** 默认折叠阈值（行数）。默认 18。设为 0 关闭折叠。 */
  collapseAfter?: number;
  /** 自定义 className（透传给根节点） */
  className?: string;
  /** 测试用：禁用 SyntaxHighlighter（强制走 plain 分支） */
  forcePlain?: boolean;
}

function _CodeBlock({ lang, code, collapseAfter = 18, className, forcePlain }: CodeBlockProps) {
  const safeLang = lang && isSupportedLang(lang) && !forcePlain ? lang : null;
  const lineCount = useMemo(() => countLines(code), [code]);
  const collapsible = collapseAfter > 0 && lineCount > collapseAfter;
  const [expanded, setExpanded] = useState(!collapsible);

  // 折叠态强制使用 plain（SyntaxHighlighter 不参与，省去折叠时不必要的高亮重算）
  const finalLang = expanded ? safeLang : null;
  const showExpandBar = collapsible;

  // 流式优化：低优先级更新代码文本。
  // useDeferredValue 在 React 18+ 把更新延后到非紧急帧，对持续 SSE push 的场景
  // 可避免每 token 都触发整棵子树 re-render。
  const deferredCode = useDeferredValue(code);

  return (
    <div
      data-testid="code-block"
      data-lang={safeLang ?? 'plain'}
      data-lines={lineCount}
      className={cn(
        'my-2 rounded-[10px] overflow-hidden border border-[var(--border)] bg-[var(--code-bg-strong)]',
        'relative group/code',
        className,
      )}
    >
      {/* 顶部语言标签 + 复制按钮 */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--border)] bg-[color-mix(in_srgb,var(--fg-0)_4%,transparent)]">
        <span className="text-[10.5px] uppercase tracking-wider text-fg2 font-mono">
          {safeLang ?? 'plain text'}
        </span>
        <CopyButton text={code} />
      </div>

      {/* 代码区 */}
      {finalLang ? (
        <SyntaxHighlighter
          key={finalLang /* 语言不变 → 不重渲染；语言变 → 强制重建 */}
          style={vscDarkPlus as Record<string, React.CSSProperties>}
          language={finalLang}
          PreTag="div"
          customStyle={{
            margin: 0,
            background: 'transparent',
            padding: '0.75rem 1rem',
            fontSize: '12.5px',
          }}
          codeTagProps={{ style: { fontFamily: 'inherit' } }}
        >
          {deferredCode}
        </SyntaxHighlighter>
      ) : (
        <pre className="font-mono text-[12.5px] text-fg1 overflow-x-auto px-4 py-3 m-0 whitespace-pre">
          <code>{deferredCode}</code>
        </pre>
      )}

      {/* 折叠展开条 */}
      {showExpandBar && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className={cn(
            'w-full flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-fg2 hover:text-fg0',
            'border-t border-[var(--border)] bg-[color-mix(in_srgb,var(--fg-0)_3%,transparent)]',
            'transition-colors',
          )}
          aria-expanded={expanded}
        >
          {expanded ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
          {expanded ? '收起' : `展开剩余 ${lineCount - collapseAfter} 行（共 ${lineCount} 行）`}
        </button>
      )}
    </div>
  );
}

export const CodeBlock = memo(_CodeBlock);
CodeBlock.displayName = 'CodeBlock';

// ============================================================
// CopyButton — 复用组件
// ============================================================
interface CopyButtonProps {
  text: string;
  className?: string;
  label?: string;
}

export const CopyButton: FC<CopyButtonProps> = ({ text, className, label }) => {
  const [copied, setCopied] = useState(false);

  const onCopy = async () => {
    let ok = false;
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        ok = true;
      } else {
        // jsdom / SSR fallback：用临时 textarea
        try {
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed';
          ta.style.opacity = '0';
          document.body.appendChild(ta);
          ta.select();
          ok = document.execCommand('copy');
          document.body.removeChild(ta);
        } catch {
          ok = false;
        }
      }
    } catch {
      ok = false;
    }
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <button
      type="button"
      onClick={onCopy}
      data-testid="copy-button"
      data-copied={copied ? 'true' : 'false'}
      aria-label={label ?? (copied ? '已复制' : '复制代码')}
      title={copied ? '已复制' : '复制'}
      className={cn(
        'inline-flex items-center gap-1 px-1.5 h-6 rounded text-[10.5px] font-mono',
        'text-fg2 hover:text-fg0 transition-colors',
        copied
          ? 'bg-emerald-500/15 text-emerald-300'
          : 'hover:bg-[color-mix(in_srgb,var(--fg-0)_8%,transparent)]',
        className,
      )}
    >
      {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
      {copied ? '已复制' : '复制'}
    </button>
  );
};

// ============================================================
// helpers
// ============================================================

function countLines(s: string): number {
  if (!s) return 0;
  let n = 1;
  for (let i = 0; i < s.length; i++) {
    if (s.charCodeAt(i) === 10) n++;
  }
  return n;
}
