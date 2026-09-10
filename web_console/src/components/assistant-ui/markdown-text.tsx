import { type FC, type ReactNode, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import { ThinkingBlock } from './ThinkingBlock';
import { isSupportedLang, SUPPORTED_LANGS } from '@/lib/syntaxLanguages';
import { uid } from '@/lib/utils';
// P2-1：把 splitThinkTags 抽到 lib/，便于单元测试（避免 React 运行时拖累）
import { splitThinkTags as _splitThinkTagsImpl } from '@/lib/splitThinkTags';

// SUPPORTED_LANGS 已通过 isSupportedLang 同模块引用，无需额外保留引用

// prism-light 是 default export，d.ts 没暴露路径；走 /dist 直接导入
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - prism-light 没有顶层 d.ts 声明
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism-light.js';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

/**
 * P1-1：从一段 Markdown 文本里提取 `<think>...</think>` 段落。
 *
 * 设计：
 *  - 兼容中英文尖括号 `<think>` / `<think>`（部分模型会省略闭合标签的 / 后缀）。
 *  - 兼容大小写 / 多对 / 跨行。
 *  - 把所有 <think> 段拼接成一段 reasoning 文本，正文按出现顺序剥掉这些段。
 *
 * 返回：
 *   - reasoning: 合并后的思考文本（空字符串表示没有思考段）
 *   - cleaned  : 已剥掉 <think> 段的纯正文（如果没有段则返回原文本）
 */
export function splitThinkTags(raw: string): { reasoning: string; cleaned: string } {
  return _splitThinkTagsImpl(raw);
}

export const MarkdownText: FC = () => {
  return (
    <MarkdownTextPrimitive
      remarkPlugins={[remarkGfm]}
      components={{
        code(props: { className?: string; children?: ReactNode }) {
          const { className, children, ...rest } = props;
          const match = /language-(\w+)/.exec(className || '');
          const isInline = !match;
          if (isInline) {
            return (
              <code className={className} {...rest}>
                {children}
              </code>
            );
          }
          const lang = match[1];
          const codeText = String(children).replace(/\n$/, '');
          if (!isSupportedLang(lang)) {
            return (
              <pre className="font-mono text-[12.5px] text-fg1 bg-[var(--code-bg)] rounded-md p-3 overflow-x-auto">
                <code className={className}>{codeText}</code>
              </pre>
            );
          }
          return (
            <SyntaxHighlighter
              style={vscDarkPlus as unknown as Record<string, React.CSSProperties>}
              language={lang}
              PreTag="div"
              customStyle={{
                margin: 0,
                background: 'transparent',
                padding: 0,
              }}
            >
              {codeText}
            </SyntaxHighlighter>
          );
        },
      }}
    />
  );
};

/**
 * P1-1：ThinkAwareMarkdown —— 在 MarkdownText 的渲染结果上再叠一层
 * `<think>...</think>` 提取。
 *
 * 用法：assistant-ui Part 渲染时若希望从文本里提取思考段，
 * 用本组件替代纯 MarkdownText：
 *   <MessagePrimitive.Parts components={{ Text: ThinkAwareMarkdown, Reasoning: ThinkingBlock, ToolFallback: ToolCallCard }} />
 *
 * 为什么单独组件：assistant-ui 的 MarkdownTextPrimitive 不暴露 children，
 * 我们需要拿到底层纯文本后再包装一层。
 */
export interface ThinkAwareMarkdownProps {
  text?: string;
  status?: { type: string };
}

export const ThinkAwareMarkdown: FC<ThinkAwareMarkdownProps> = ({ text, status }) => {
  const { reasoning, cleaned } = useMemo(() => splitThinkTags(text ?? ''), [text]);
  const hasReasoning = reasoning.length > 0;

  return (
    <div className="think-aware-markdown">
      {hasReasoning && (
        <ThinkingBlock
          text={reasoning}
          status={status ?? { type: 'complete' }}
          // 思考段使用稳定 key，避免重渲染时闪烁
          key={`reasoning-${uid()}`}
        />
      )}
      {cleaned ? (
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code(props: { className?: string; children?: ReactNode }) {
              const { className, children, ...rest } = props;
              const match = /language-(\w+)/.exec(className || '');
              const isInline = !match;
              if (isInline) {
                return (
                  <code className={className} {...rest}>
                    {children}
                  </code>
                );
              }
              const lang = match[1];
              const codeText = String(children).replace(/\n$/, '');
              if (!isSupportedLang(lang)) {
                return (
                  <pre className="font-mono text-[12.5px] text-fg1 bg-[var(--code-bg)] rounded-md p-3 overflow-x-auto">
                    <code className={className}>{codeText}</code>
                  </pre>
                );
              }
              return (
                <SyntaxHighlighter
                  style={vscDarkPlus as unknown as Record<string, React.CSSProperties>}
                  language={lang}
                  PreTag="div"
                  customStyle={{ margin: 0, background: 'transparent', padding: 0 }}
                >
                  {codeText}
                </SyntaxHighlighter>
              );
            },
          }}
        >
          {cleaned}
        </ReactMarkdown>
      ) : !hasReasoning ? null : null}
    </div>
  );
};

export default MarkdownText;
