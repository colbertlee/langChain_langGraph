import { describe, it, expect } from 'vitest';
// P2-1：从 lib/ 直接导入实现，避免 markdown-text.tsx 拖入 React 运行时
import { splitThinkTags } from '@/lib/splitThinkTags';

describe('splitThinkTags (P1-1)', () => {
  it('没有 think 标签时原样返回', () => {
    const raw = '这是普通回答。';
    const { reasoning, cleaned } = splitThinkTags(raw);
    expect(reasoning).toBe('');
    expect(cleaned).toBe('这是普通回答。');
  });

  it('空字符串不会抛错', () => {
    const { reasoning, cleaned } = splitThinkTags('');
    expect(reasoning).toBe('');
    expect(cleaned).toBe('');
  });

  it('单个 think 段：分离思考与正文', () => {
    const raw = '<think>\n我需要先做规划。\n</think>\n## 回答\n好的。';
    const { reasoning, cleaned } = splitThinkTags(raw);
    expect(reasoning).toBe('我需要先做规划。');
    expect(cleaned).toBe('## 回答\n好的。');
  });

  it('多个 think 段：合并到一个 reasoning', () => {
    const raw = '<think>\n第一阶段：分析。\n</think>中间文字<think>\n第二阶段：验证。\n</think>';
    const { reasoning, cleaned } = splitThinkTags(raw);
    expect(reasoning).toBe('第一阶段：分析。\n\n第二阶段：验证。');
    expect(cleaned).toBe('中间文字');
  });

  it('跨行 think 段：保留换行', () => {
    const raw = '<think>\nLine1\nLine2\nLine3\n</think>\n正文';
    const { reasoning, cleaned } = splitThinkTags(raw);
    expect(reasoning).toBe('Line1\nLine2\nLine3');
    expect(cleaned).toBe('正文');
  });

  it('大小写不敏感', () => {
    const raw = '<Think>\nupper\n</Think>\nbody';
    const { reasoning, cleaned } = splitThinkTags(raw);
    expect(reasoning).toBe('upper');
    expect(cleaned).toBe('body');
  });

  it('只有 think 没有正文时，cleaned 为空', () => {
    const raw = '<think>\nonly thought\n</think>';
    const { reasoning, cleaned } = splitThinkTags(raw);
    expect(reasoning).toBe('only thought');
    expect(cleaned).toBe('');
  });
});
