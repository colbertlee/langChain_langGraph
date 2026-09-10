import { describe, it, expect, beforeAll, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SessionSidebar } from './SessionSidebar';
import { useChatStore } from '@/stores/chatStore';
import { useUIStore } from '@/stores/uiStore';
import { useAgentStore } from '@/stores/agentStore';

// mock api module
vi.mock('@/lib/api', async () => {
  return {
    api: {
      clear: vi.fn().mockResolvedValue({ success: true, message: 'cleared' }),
    },
  };
});

describe('SessionSidebar', () => {
  beforeAll(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  beforeEach(async () => {
    // 重置 chatStore 状态
    useChatStore.setState({
      sessions: {},
      activeSessionId: '',
      messages: {},
    });
    useUIStore.setState({
      sessionsCollapsed: false,
    });
    // 重置 mock 计数
    const { api } = await import('@/lib/api');
    (api.clear as unknown as { mockClear: () => void }).mockClear();
  });

  it('空 session 列表显示"暂无 Session"', () => {
    render(<SessionSidebar />);
    expect(screen.getByText(/暂无 Session/)).toBeInTheDocument();
  });

  it('有 session 时显示列表', () => {
    useChatStore.setState({
      sessions: {
        a: { id: 'a', title: '会话 A', createdAt: 100, updatedAt: 100 },
        b: { id: 'b', title: '会话 B', createdAt: 200, updatedAt: 200 },
      },
      activeSessionId: 'a',
    });
    render(<SessionSidebar />);
    expect(screen.getByText('会话 A')).toBeInTheDocument();
    expect(screen.getByText('会话 B')).toBeInTheDocument();
  });

  it('点击 session 切换 active', () => {
    useChatStore.setState({
      sessions: {
        a: { id: 'a', title: '会话 A', createdAt: 100, updatedAt: 100 },
        b: { id: 'b', title: '会话 B', createdAt: 200, updatedAt: 200 },
      },
      activeSessionId: 'a',
    });
    render(<SessionSidebar />);
    fireEvent.click(screen.getByText('会话 B'));
    expect(useChatStore.getState().activeSessionId).toBe('b');
  });

  it('点击"+ 新建"按钮创建一个新 session', () => {
    useChatStore.setState({
      sessions: {
        a: { id: 'a', title: 'A', createdAt: 100, updatedAt: 100 },
      },
      activeSessionId: 'a',
    });
    render(<SessionSidebar />);
    const buttons = screen.getAllByTitle(/新建 Session/);
    fireEvent.click(buttons[0]);
    const after = useChatStore.getState();
    expect(Object.keys(after.sessions).length).toBe(2);
    expect(after.activeSessionId).not.toBe('a');
  });

  it('点击"清空当前对话"弹出确认对话框', () => {
    useChatStore.setState({
      sessions: {
        a: { id: 'a', title: '我的会话', createdAt: 100, updatedAt: 100 },
      },
      activeSessionId: 'a',
    });
    render(<SessionSidebar />);
    fireEvent.click(screen.getByTestId('clear-conversation-btn'));
    expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument();
    // "我的会话" 在 dialog 标题 + body 都出现 → 用 getAllByText
    expect(screen.getAllByText(/我的会话/).length).toBeGreaterThan(0);
  });

  it('确认清空后调用 api.clear + 清空 messages', async () => {
    const { api } = await import('@/lib/api');
    useChatStore.setState({
      sessions: {
        a: { id: 'a', title: 'A', createdAt: 100, updatedAt: 100 },
      },
      activeSessionId: 'a',
      messages: {
        a: [
          {
            id: 'm1',
            sessionId: 'a',
            role: 'user',
            content: 'hi',
            toolCalls: [],
            createdAt: 1,
          },
        ],
      },
    });
    render(<SessionSidebar />);
    fireEvent.click(screen.getByTestId('clear-conversation-btn'));
    fireEvent.click(screen.getByTestId('confirm-yes'));
    await waitFor(() => {
      expect(api.clear).toHaveBeenCalled();
    });
    await waitFor(() => {
      expect((useChatStore.getState().messages.a ?? [])).toEqual([]);
    });
  });

  it('取消清空对话框不会触发 api.clear', async () => {
    const { api } = await import('@/lib/api');
    useChatStore.setState({
      sessions: {
        a: { id: 'a', title: 'A', createdAt: 100, updatedAt: 100 },
      },
      activeSessionId: 'a',
    });
    render(<SessionSidebar />);
    fireEvent.click(screen.getByTestId('clear-conversation-btn'));
    fireEvent.click(screen.getByText('取消'));
    // api.clear 不应被调用
    expect(api.clear).not.toHaveBeenCalled();
  });

  it('sessionsCollapsed=true 时只显示图标列', () => {
    useUIStore.setState({ sessionsCollapsed: true });
    render(<SessionSidebar />);
    expect(screen.queryByTestId('session-sidebar')).not.toBeInTheDocument();
    // 收起态有展开按钮
    expect(screen.getByLabelText(/展开 Session 列表/)).toBeInTheDocument();
  });
});

/**
 * 回归测试套件（草稿跨 Session 污染 & 全新 Session 初始 input 为空）。
 *
 * Bug 描述：
 *   1) 在 Session A 输入了一段未发送的草稿，切换到 Session B 后，
 *      B 的输入框内仍然带出 A 的草稿。
 *   2) 在某些新 Session 下按 Ctrl+V 无法粘贴文本。
 *
 * 修复策略：
 *   - Composer 子树用 `key={activeSessionId}` 包裹 → 切换 Session 时
 *     React 直接销毁旧的 ComposerPrimitive 树（含未发送的草稿 + 上传中的附件），
 *     重建全新的 Input State。
 *   - chatStore.newSession() 在切到新 session 时，新 sessionId 的
 *     messages/attachments 都是空数组，且与上一个 session 完全隔离。
 *
 * 注意：这些测试验证的是**结构契约**（"新 session 的 messages 必须为空"）
 * —— 真正的 "input value === ''" 断言放在 ChatPage 渲染测试里，因为
 * 需要 mount 完整的 Thread/Composer 才能拿到 textarea。
 */
describe('SessionSidebar / chatStore — 草稿隔离回归', () => {
  beforeEach(async () => {
    useChatStore.setState({
      sessions: {},
      activeSessionId: '',
      messages: {},
      attachments: {},
    });
    useUIStore.setState({ sessionsCollapsed: false });
    const { api } = await import('@/lib/api');
    (api.clear as unknown as { mockClear: () => void }).mockClear();
  });

  it('新建 session 时，该 sessionId 对应的 messages 数组必须为空（防草稿残留）', () => {
    // 模拟 Session A 里已经积累了 3 条消息 + 2 个附件
    const idA = useChatStore.getState().newSession();
    useChatStore.setState((st) => ({
      messages: {
        ...st.messages,
        [idA]: [
          {
            id: 'm1',
            sessionId: idA,
            role: 'user',
            content: '上一轮的草稿',
            toolCalls: [],
            createdAt: Date.now(),
          },
        ],
      },
      attachments: {
        ...st.attachments,
        [idA]: [
          {
            id: 'a1',
            name: 'old.png',
            url: '/uploads/old.png',
            contentType: 'image/png',
            size: 1024,
            uploadedAt: Date.now(),
          },
        ],
      },
    }));

    // 用户点了"新建 Session"
    const idB = useChatStore.getState().newSession();
    const after = useChatStore.getState();

    // ✅ 核心断言：新 session 的 messages 必须为空（不是"上一次的草稿"）
    expect(after.messages[idB]).toEqual([]);
    // 同样 attachments 也必须为空
    expect(after.attachments[idB]).toEqual([]);
    // B 不能误带 A 的草稿
    expect(after.messages[idB]?.[0]?.content ?? '').not.toBe('上一轮的草稿');
    // active 已切到 B
    expect(after.activeSessionId).toBe(idB);
    expect(idA).not.toBe(idB);
  });

  it('切换 activeSessionId（setActive）时，messages / attachments 字典里两个 sessionId 的内容互不影响', () => {
    const idA = useChatStore.getState().newSession();
    const idB = useChatStore.getState().newSession();
    // 当前 active 是 B（B 是最后 newSession 创建的）
    useChatStore.setState((st) => ({
      messages: {
        ...st.messages,
        [idA]: [
          {
            id: 'a1',
            sessionId: idA,
            role: 'user',
            content: 'A 的草稿',
            toolCalls: [],
            createdAt: Date.now(),
          },
        ],
        [idB]: [
          {
            id: 'b1',
            sessionId: idB,
            role: 'user',
            content: 'B 的草稿',
            toolCalls: [],
            createdAt: Date.now(),
          },
        ],
      },
    }));

    // 切回 A，再切到 B，再切回 A —— 每次 messages 字典里的两个 sessionId 数据应完全保留
    useChatStore.getState().setActive(idA);
    expect(useChatStore.getState().messages[idA]?.[0]?.content).toBe('A 的草稿');
    useChatStore.getState().setActive(idB);
    expect(useChatStore.getState().messages[idB]?.[0]?.content).toBe('B 的草稿');
    useChatStore.getState().setActive(idA);
    expect(useChatStore.getState().messages[idA]?.[0]?.content).toBe('A 的草稿');
  });

  it('点击侧栏里的某个 session 项切换 active 后，前一个 session 的草稿不会被移到新 session 名下', () => {
    const idA = useChatStore.getState().newSession();
    const idB = useChatStore.getState().newSession();
    // 在 A 里追加一条 user 消息（模拟未发送草稿被保存到 messages 字典的边界场景）
    useChatStore.getState().appendMessage(idA, {
      id: 'draftA',
      sessionId: idA,
      role: 'user',
      content: 'A 的草稿',
      toolCalls: [],
      createdAt: Date.now(),
    });

    // 把 A 的 title 强制写回 "A"（appendMessage 会自动用首条消息做 title，
    // 这里 override 一下让断言稳定）
    useChatStore.getState().renameSession(idA, 'A');
    useChatStore.getState().renameSession(idB, 'B');
    // A 的 updatedAt 比 B 旧，所以列表里 B 排第一（updatedAt 倒序）
    useChatStore.setState((st) => ({
      sessions: {
        ...st.sessions,
        [idA]: { ...st.sessions[idA], updatedAt: 1 },
        [idB]: { ...st.sessions[idB], updatedAt: 2 },
      },
      activeSessionId: idB,
    }));
    render(<SessionSidebar />);
    // 找到 title 文本恰好为 "A" 的按钮（不是包含 "A" 的所有元素）
    const buttons = screen.getAllByRole('button');
    const titleButtonA = buttons.find(
      (b) => b.textContent?.trim().startsWith('A') && b.querySelector('span')?.textContent === 'A',
    );
    expect(titleButtonA).toBeDefined();
    fireEvent.click(titleButtonA!);
    expect(useChatStore.getState().activeSessionId).toBe(idA);

    // 切换后，两个 session 的 messages 各自保持原样
    expect(useChatStore.getState().messages[idA]?.[0]?.content).toBe('A 的草稿');
    expect(useChatStore.getState().messages[idB]).toEqual([]);
  });
});

// ============================================================
// v2.1 — Agent 切换
// ============================================================
describe('SessionSidebar / v2.1 Agent 切换', () => {
  beforeAll(() => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
  });

  beforeEach(async () => {
    useChatStore.setState({
      sessions: {
        a: { id: 'a', title: 'A', createdAt: 100, updatedAt: 100 },
      },
      activeSessionId: 'a',
      messages: {},
    });
    // 直接 import & 重置 agentStore（避免 loadPresets 的真实 fetch）
    useAgentStore.setState({
      presets: [
        {
          id: 'builtin-general',
          name: '通用助手',
          description: '通用',
          avatar: '🤖',
          system_prompt: '',
          temperature: 0.7,
          tools: [],
          builtin: true,
          created_at: 1,
          updated_at: 1,
        },
        {
          id: 'builtin-refactor',
          name: '代码重构专家',
          description: '重构',
          avatar: '🛠️',
          system_prompt: '',
          temperature: 0.3,
          tools: ['python_exec'],
          builtin: true,
          created_at: 2,
          updated_at: 2,
        },
      ],
      defaultAgentId: 'builtin-general',
      sessionAgentMap: {},
      loaded: true,
      loading: false,
    });
  });

  it('默认渲染 agent switcher 且选中 default agent', () => {
    render(<SessionSidebar />);
    const sel = screen.getByTestId('agent-switcher') as HTMLSelectElement;
    expect(sel).toBeInTheDocument();
    expect(sel.value).toBe('builtin-general');
  });

  it('切换 agent 写入 sessionAgentMap', () => {
    render(<SessionSidebar />);
    const sel = screen.getByTestId('agent-switcher') as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: 'builtin-refactor' } });
    expect(useAgentStore.getState().sessionAgentMap.a).toBe('builtin-refactor');
  });

  it('点击 "管理" 按钮打开 AgentConfigModal', () => {
    render(<SessionSidebar />);
    fireEvent.click(screen.getByTestId('open-agent-config'));
    expect(screen.getByTestId('agent-config-modal')).toBeInTheDocument();
  });

  it('Modal 中切换 preset 列表 → 右侧表单同步更新', () => {
    render(<SessionSidebar />);
    fireEvent.click(screen.getByTestId('open-agent-config'));
    const items = screen.getAllByTestId('agent-preset-item');
    fireEvent.click(items[1]); // builtin-refactor
    const nameInput = screen.getByTestId('agent-name-input') as HTMLInputElement;
    expect(nameInput.value).toBe('代码重构专家');
  });
});
