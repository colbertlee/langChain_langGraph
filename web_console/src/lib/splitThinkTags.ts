/**
 * P1-1 — splitThinkTags：从 Markdown 文本中提取 `<think>...</think>` 段。
 *
 * 设计：
 *  - 兼容中英文尖括号 `<think>` / `<think>`（部分模型会省略闭合标签的 / 后缀）。
 *  - 兼容大小写 / 多对 / 跨行。
 *  - 把所有 <think> 段拼接成一段 reasoning 文本，正文按出现顺序剥掉这些段。
 *
 * 返回：
 *   - reasoning: 合并后的思考文本（空字符串表示没有思考段）
 *   - cleaned  : 已剥掉 <think> 段的纯正文（如果没有段则返回原文本）
 *
 * 抽到 lib/ 而非 assistant-ui/，便于在 jsdom/node 环境单元测试（避免引入 React 运行时）。
 */

export interface SplitThinkTagsResult {
  reasoning: string;
  cleaned: string;
}

export function splitThinkTags(raw: string): SplitThinkTagsResult {
  if (!raw) return { reasoning: '', cleaned: '' };
  // 大小写不敏感的快速预检
  if (!/<think[\s>]/i.test(raw)) {
    return { reasoning: '', cleaned: raw };
  }
  // 用非贪婪正则；点匹配换行；大小写不敏感
  const re = /<think>([\s\S]*?)<\/think>/gi;
  const thoughts: string[] = [];
  const cleaned = raw.replace(re, (_m, inner: string) => {
    thoughts.push(inner.trim());
    return '';
  });
  return {
    reasoning: thoughts.join('\n\n').trim(),
    cleaned: cleaned.trim(),
  };
}
