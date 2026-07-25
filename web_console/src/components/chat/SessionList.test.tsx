import { describe, it, expect, beforeEach } from 'vitest';
import { act, render, screen, fireEvent, within } from '@testing-library/react';
import { SessionList } from './SessionList';
import { useChatStore } from '@/stores/chatStore';

// Mock assistant-ui 提供的 aui（避免在 store 之外抛错）
vi.mock('@assistant-ui/react', () => ({
  useAui: () => ({
    threads: () => ({ switchToNewThread: () => {}, switchToThread: () => {} }),
  }),
  useAuiState: () => null,
}));

describe('SessionList', () => {
  beforeEach(() => {
    useChatStore.getState().clearAll();
  });

  it('渲染「新建会话」按钮', () => {
    render(<SessionList />);
    expect(screen.getByText(/新建会话/)).toBeInTheDocument();
  });

  it('显示初始会话标题「新会话」', () => {
    render(<SessionList />);
    expect(screen.getAllByText('新会话').length).toBeGreaterThan(0);
  });

  it('点击「新建会话」会再插入一条记录', () => {
    render(<SessionList />);
    const before = Object.keys(useChatStore.getState().sessions).length;
    fireEvent.click(screen.getByText(/新建会话/));
    const after = Object.keys(useChatStore.getState().sessions).length;
    expect(after).toBe(before + 1);
  });

  it('多个会话按 updatedAt 倒序展示', () => {
    act(() => {
      useChatStore.getState().clearAll();
    });
    const oldId = useChatStore.getState().activeSessionId;
    act(() => {
      useChatStore.getState().renameSession(oldId, 'OLD');
      useChatStore.setState((st) => ({
        sessions: {
          ...st.sessions,
          [oldId]: { ...st.sessions[oldId], updatedAt: 0 },
        },
      }));
    });

    act(() => {
      useChatStore.getState().newSession();
    });
    const newId = useChatStore.getState().activeSessionId;
    act(() => {
      useChatStore.getState().renameSession(newId, 'NEW');
      useChatStore.setState((st) => ({
        sessions: {
          ...st.sessions,
          [newId]: { ...st.sessions[newId], updatedAt: Date.now() + 1_000_000 },
        },
      }));
    });

    const { container } = render(<SessionList />);
    const items = container.querySelectorAll('.text-fg0.truncate.font-medium');
    expect(items[0]?.textContent).toBe('NEW');
    expect(items[1]?.textContent).toBe('OLD');
  });
});
