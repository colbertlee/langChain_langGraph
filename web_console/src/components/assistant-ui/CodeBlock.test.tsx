import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { CodeBlock, CopyButton } from './CodeBlock';

// 在 jsdom 里 mock navigator.clipboard.writeText 返回成功（真实浏览器默认行为）
beforeEach(() => {
  Object.assign(navigator, {
    clipboard: {
      writeText: vi.fn().mockResolvedValue(undefined),
    },
  });
});

// 强制 plain text 模式（避免 SyntaxHighlighter 在 jsdom 里抛错）
describe('CodeBlock (plain mode)', () => {
  beforeAll(() => {
    // mock console.error 以捕获 jsdom 高亮错误（不抛）
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('未识别语言按 plain text 渲染', () => {
    render(<CodeBlock lang="unknown-lang" code="hello" />);
    expect(screen.getByTestId('code-block')).toHaveAttribute('data-lang', 'plain');
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('复制按钮存在且可点击', () => {
    render(<CodeBlock lang={null} code="copy-me" />);
    const btn = screen.getByTestId('copy-button');
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveAttribute('data-copied', 'false');
  });

  it('点击复制按钮后状态切换为已复制（异步）', async () => {
    render(<CodeBlock lang={null} code="copy-me" />);
    const btn = screen.getByTestId('copy-button');
    fireEvent.click(btn);
    // onCopy 异步 → waitFor 等 setState 落地
    await waitFor(() => {
      expect(btn).toHaveAttribute('data-copied', 'true');
    });
    expect(btn).toHaveTextContent('已复制');
  });

  it('行数超过阈值时显示折叠按钮', () => {
    const long = Array.from({ length: 30 }, (_, i) => `line ${i}`).join('\n');
    render(<CodeBlock lang={null} code={long} collapseAfter={18} />);
    const btn = screen.getByRole('button', { name: /展开剩余/ });
    expect(btn).toBeInTheDocument();
    expect(screen.getByTestId('code-block')).toHaveAttribute('data-lines', '30');
  });

  it('行数未超过阈值时无折叠按钮', () => {
    render(<CodeBlock lang={null} code="a\nb\nc" collapseAfter={18} />);
    expect(screen.queryByRole('button', { name: /展开剩余/ })).not.toBeInTheDocument();
  });

  it('点击折叠按钮可切换展开/收起', () => {
    const long = Array.from({ length: 30 }, (_, i) => `line ${i}`).join('\n');
    render(<CodeBlock lang={null} code={long} collapseAfter={18} />);
    const expandBtn = screen.getByRole('button', { name: /展开剩余/ });
    fireEvent.click(expandBtn);
    expect(screen.getByRole('button', { name: /收起/ })).toBeInTheDocument();
  });

  it('collapseAfter=0 关闭折叠', () => {
    const long = Array.from({ length: 50 }, () => 'x').join('\n');
    render(<CodeBlock lang={null} code={long} collapseAfter={0} />);
    expect(screen.queryByRole('button', { name: /展开剩余/ })).not.toBeInTheDocument();
  });
});

describe('CopyButton', () => {
  beforeAll(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  it('默认显示"复制"', () => {
    render(<CopyButton text="x" />);
    expect(screen.getByTestId('copy-button')).toHaveTextContent('复制');
  });

  it('点击后切换为"已复制"', async () => {
    render(<CopyButton text="x" />);
    fireEvent.click(screen.getByTestId('copy-button'));
    await waitFor(() => {
      expect(screen.getByTestId('copy-button')).toHaveTextContent('已复制');
    });
  });
});
