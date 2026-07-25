/**
 * Markdown 代码块高亮的语言注册表。
 *
 * 为控制 bundle 体积，仅 import 实际可能用到的语言。
 * 如需新增语言：
 * 1. 在下方 PRISM_LANGUAGES 加 entry：`{ lang: 'kotlin', aliases: ['kt'], module: () => import('react-syntax-highlighter/dist/esm/languages/prism/kotlin') }`
 * 2. 重新 `npm run build` — Vite 会自动 tree-shake 未引用的语言
 *
 * 注意：react-syntax-highlighter 的 Prism 是 default export，
 * 这里也通过 default 拿取 refractor/register API。
 */
// prism-light 是 default export，d.ts 没暴露路径；走 /dist 直接导入
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore - prism-light 没有顶层 d.ts 声明
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism-light.js';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp';
import xmlDoc from 'react-syntax-highlighter/dist/esm/languages/prism/markup';

/** 语言定义：标准 lang 名 → prism module + 别名列表 */
interface LanguageEntry {
  lang: string;
  module: unknown;
  aliases: string[];
}

const PRISM_LANGUAGES: LanguageEntry[] = [
  { lang: 'javascript', module: javascript, aliases: ['js', 'jsx'] },
  { lang: 'typescript', module: typescript, aliases: ['ts', 'tsx'] },
  { lang: 'python', module: python, aliases: ['py'] },
  { lang: 'bash', module: bash, aliases: ['sh', 'shell'] },
  { lang: 'json', module: json, aliases: [] },
  { lang: 'css', module: css, aliases: [] },
  { lang: 'sql', module: sql, aliases: [] },
  { lang: 'yaml', module: yaml, aliases: ['yml'] },
  { lang: 'markdown', module: markdown, aliases: ['md'] },
  { lang: 'go', module: go, aliases: [] },
  { lang: 'rust', module: rust, aliases: ['rs'] },
  { lang: 'java', module: java, aliases: [] },
  { lang: 'cpp', module: cpp, aliases: ['c'] },
  { lang: 'markup', module: xmlDoc, aliases: ['html', 'xml', 'vue'] },
];

/** 全部合法语言标识（含别名）— 用于 fenced code block 探测 */
export const SUPPORTED_LANGS: ReadonlySet<string> = (() => {
  const s = new Set<string>();
  for (const e of PRISM_LANGUAGES) {
    s.add(e.lang);
    for (const a of e.aliases) s.add(a);
  }
  return s;
})();

// prism-light 的 SyntaxHighlighter 是 default export，
// 自带 registerLanguage(name, langModule) 静态方法
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SH = SyntaxHighlighter as unknown as {
  registerLanguage: (name: string, lang: unknown) => void;
  alias?: (name: string, aliases: string[]) => void;
};
for (const e of PRISM_LANGUAGES) {
  SH.registerLanguage(e.lang, e.module);
  for (const a of e.aliases) SH.registerLanguage(a, e.module);
}

/** 用户可调整的列表（用于运行时按需扩展 / 测试） */
export function isSupportedLang(lang: string): boolean {
  return SUPPORTED_LANGS.has(lang);
}