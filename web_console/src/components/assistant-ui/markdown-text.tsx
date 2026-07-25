import { type FC, type ReactNode } from 'react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import remarkGfm from 'remark-gfm';

// prism-light 是 default export，d.ts 没暴露路径；走 /dist 直接导入
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - prism-light 没有顶层 d.ts 声明
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism-light.js';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';

import { isSupportedLang, SUPPORTED_LANGS } from '@/lib/syntaxLanguages';

// 通过 import 触发 side-effect 注册（即使下面没有显式引用）
// eslint-disable-next-line @typescript-eslint/no-unused-expressions
[SUPPORTED_LANGS];

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
              <pre className="font-mono text-[12.5px] text-fg1 bg-[rgba(0,0,0,0.4)] rounded-md p-3 overflow-x-auto">
                <code className={className}>{codeText}</code>
              </pre>
            );
          }
          return (
            <SyntaxHighlighter
              style={vscDarkPlus as Record<string, React.CSSProperties>}
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