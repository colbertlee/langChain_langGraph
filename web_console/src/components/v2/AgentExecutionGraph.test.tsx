/**
 * AgentExecutionGraph.test.tsx — v2.2.3
 *
 * 覆盖：
 *  1) AgentExecutionGraph 组件渲染
 *     - 空轨迹时不渲染
 *     - 多 agent_switch 事件下节点按时间顺序追加并展示 reason
 *     - agent_done 事件让节点显示 "结束" 标记
 *  2) chatStore.agentEvents 持久化（F5 恢复）
 *     - 写入新事件 → store 状态正确
 *     - persist 升级到 v4 后旧数据可平滑降级
 *  3) sseParser normalize 新事件类型（agent_switch / agent_done）
 *  4) AgentExecutionGraph 嵌套 ApprovalCard 交互
 *     - 当节点携带 requestId 且 chatStore.approvalCards 有对应卡片时，
 *       渲染迷你审批卡（CompactApprovalCard）；
 *     - 点击 "允许" 调用 api.chatApprove 并 resolveApproval；
 *     - 点击 "编辑参数" 切换为 textarea + "用编辑后参数执行" 二次确认。
 *  5) useAgentLocalRuntime 集成（独立 SSE → store + 消息流）
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { useChatStore } from '@/stores/chatStore';
import {
  AgentExecutionGraph,
  parseAgentEvent,
} from '@/components/v2/AgentExecutionGraph';
import { normalizeSseEvents, parseSseStream } from '@/lib/sseParser';

// ---- mocks ---------------------------------------------------------------
vi.mock('@/lib/api', async () => {
  return {
    api: {
      chatApprove: vi.fn().mockResolvedValue({ ok: true, request_id: 'r1' }),
      chatReject: vi.fn().mockResolvedValue({ ok: true, request_id: 'r1' }),
    },
  };
});

beforeEach(async () => {
  useChatStore.getState().clearAll();
  const api = (await import('@/lib/api')).api;
  (api.chatApprove as ReturnType<typeof vi.fn>).mockClear();
  (api.chatReject as ReturnType<typeof vi.fn>).mockClear();
});

// =============================================================================================
// 1) 组件渲染基础
// =============================================================================================

describe('AgentExecutionGraph 基础渲染', () => {
  it('空轨迹时不渲染任何节点', () => {
    const sid = useChatStore.getState().activeSessionId;
    const { container } = render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    // agent-execution-graph 容器不应该出现（无节点）
    expect(container.querySelector('[data-testid="agent-execution-graph"]')).toBeNull();
  });

  it('单个 agent_switch 节点展开后展示 reason / agent', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'research_worker',
      reason: '需要查实时新闻',
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    expect(screen.getByTestId('agent-execution-graph')).toBeTruthy();
    const nodes = screen.getAllByTestId('agent-node');
    expect(nodes).toHaveLength(1);
    expect(nodes[0].getAttribute('data-agent')).toBe('research_worker');
    // badge 文本：research_worker → RSC
    expect(screen.getByTestId('agent-node-badge').textContent).toContain('RSC');
    expect(screen.getByTestId('agent-node-reason').textContent).toContain(
      '需要查实时新闻',
    );
  });

  it('多个 agent_switch 节点按顺序渲染，节点计数正确', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'supervisor',
      reason: '分析用户意图',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'rag_worker',
      reason: '查本地知识库',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: '跑计算',
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    const nodes = screen.getAllByTestId('agent-node');
    expect(nodes).toHaveLength(3);
    expect(nodes.map((n) => n.getAttribute('data-agent'))).toEqual([
      'supervisor',
      'rag_worker',
      'code_worker',
    ]);
    expect(screen.getByTestId('agent-execution-graph-count').textContent).toContain(
      '3 节点',
    );
  });

  it('FINISH / done 节点显示 "结束" 标记', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'supervisor',
      reason: 'go',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'done',
      agent: 'FINISH',
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    const nodes = screen.getAllByTestId('agent-node');
    expect(nodes).toHaveLength(2);
    // 最后一个节点 (FINISH) 的 agent 属性
    expect(nodes[1].getAttribute('data-agent')).toBe('FINISH');
    // "结束" 文本应在树中（用 partial match 查找）
    const allText = document.body.textContent ?? '';
    expect(allText).toContain('结束');
  });

  it('折叠时点击 toggle 展开节点列表', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'research_worker',
      reason: 'search',
    });
    // 默认收起
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded={false} />);
    expect(screen.queryByTestId('agent-execution-graph-list')).toBeNull();
    fireEvent.click(screen.getByTestId('agent-execution-graph-toggle'));
    expect(screen.getByTestId('agent-execution-graph-list')).toBeTruthy();
    expect(screen.getAllByTestId('agent-node')).toHaveLength(1);
  });

  it('节点 durationMs 在 > 0 时显示', async () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'supervisor',
      reason: 'go',
    });
    // 等 60ms 再追加第二个节点，保证 durationMs > 0
    await new Promise((r) => setTimeout(r, 60));
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'next',
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    const dur = screen.getAllByTestId('agent-node-duration');
    expect(dur.length).toBeGreaterThan(0);
    // 文本是形如 "1ms" / "60ms" 的；至少要含 "ms"
    expect(dur[0].textContent ?? '').toMatch(/ms/);
  });
});

// =============================================================================================
// 2) chatStore.agentEvents 持久化 + F5 恢复
// =============================================================================================

describe('chatStore.agentEvents F5 持久化', () => {
  it('appendAgentEvent 写入并按调用顺序累加', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'supervisor',
      reason: 'r0',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'r1',
    });
    const events = useChatStore.getState().agentEvents[sid];
    expect(events).toHaveLength(2);
    expect(events[0].agent).toBe('supervisor');
    expect(events[1].agent).toBe('code_worker');
    // 自动 id / ts / durationMs
    expect(events[0].id).toBeTruthy();
    expect(typeof events[0].ts).toBe('number');
    expect(events[1].durationMs).toBeGreaterThanOrEqual(0);
  });

  it('clearAgentEvents 清空当前 session 轨迹', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'rag_worker',
      reason: 'r',
    });
    expect(useChatStore.getState().agentEvents[sid]).toHaveLength(1);
    useChatStore.getState().clearAgentEvents(sid);
    expect(useChatStore.getState().agentEvents[sid]).toEqual([]);
  });

  it('getAgentEvents 不存在 session 返回 []', () => {
    const events = useChatStore.getState().getAgentEvents('non-existent');
    expect(events).toEqual([]);
  });

  it('newSession 创建时 agentEvents 为空数组', () => {
    const id = useChatStore.getState().newSession();
    expect(useChatStore.getState().agentEvents[id]).toEqual([]);
  });

  it('deleteSession 同时清理 agentEvents', () => {
    const sid1 = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid1, {
      sessionId: sid1,
      type: 'switch',
      agent: 'rag_worker',
      reason: 'r',
    });
    const sid2 = useChatStore.getState().newSession();
    useChatStore.getState().deleteSession(sid1);
    expect(useChatStore.getState().agentEvents[sid1]).toBeUndefined();
    // 当前 activeSessionId 应切到 sid2（因为 sid1 被删除）
    expect(useChatStore.getState().activeSessionId).toBe(sid2);
  });

  it('持久化：写入后从 localStorage 重新读取可恢复（F5 模拟）', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'r',
    });
    // 模拟 F5：直接读 localStorage
    const raw = localStorage.getItem('agent-console-chat');
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw ?? '{}');
    const persistedState = parsed?.state ?? {};
    expect(persistedState.agentEvents?.[sid]?.[0]?.agent).toBe('code_worker');
    expect(persistedState.agentEvents?.[sid]?.[0]?.reason).toBe('r');
  });
});

// =============================================================================================
// 3) parseAgentEvent / sseParser.normalize
// =============================================================================================

describe('parseAgentEvent (SSE event 解析)', () => {
  it('agent_switch 解析为完整结构', () => {
    const out = parseAgentEvent({
      type: 'agent_switch',
      agent: 'code_worker',
      reason: 'run python',
      request_id: 'r1',
    });
    expect(out).toEqual({
      type: 'agent_switch',
      agent: 'code_worker',
      reason: 'run python',
      requestId: 'r1',
    });
  });

  it('agent_done 解析', () => {
    const out = parseAgentEvent({ type: 'agent_done', agent: 'FINISH' });
    expect(out).toEqual({ type: 'agent_done', agent: 'FINISH' });
  });

  it('缺字段 / 非法 type 返回 null', () => {
    expect(parseAgentEvent(null)).toBeNull();
    expect(parseAgentEvent({})).toBeNull();
    expect(parseAgentEvent({ type: 'agent_switch' })).toBeNull(); // agent 缺
    expect(parseAgentEvent({ type: 'unknown' })).toBeNull();
  });
});

describe('sseParser.normalizeSseEvents (v2.2.3)', () => {
  it('agent_switch 标准化为 agent-switch', () => {
    const evts = parseSseStream(
      [
        'event: agent_switch',
        'data: {"type":"agent_switch","agent":"research_worker","reason":"q"}',
        '',
        '',
      ].join('\n'),
    );
    const out = normalizeSseEvents(evts);
    expect(out).toHaveLength(1);
    expect(out[0].kind).toBe('agent-switch');
    if (out[0].kind === 'agent-switch') {
      expect(out[0].agent).toBe('research_worker');
      expect(out[0].reason).toBe('q');
    }
  });

  it('agent_done 标准化为 agent-done', () => {
    const evts = parseSseStream(
      'event: agent_done\ndata: {"type":"agent_done","agent":"FINISH"}\n\n',
    );
    const out = normalizeSseEvents(evts);
    expect(out).toHaveLength(1);
    expect(out[0]).toEqual({ kind: 'agent-done', agent: 'FINISH' });
  });

  it('混合事件：text + agent_switch + approval_required + agent_done', () => {
    const raw = [
      'event: chunk',
      'data: {"type":"chunk","data":"hello"}',
      '',
      'event: agent_switch',
      'data: {"type":"agent_switch","agent":"code_worker","reason":"run"}',
      '',
      'event: approval_required',
      'data: {"type":"approval_required","request_id":"r1","tool_name":"python_interpreter","tool_args":{"code":"x"},"reason":"need ok"}',
      '',
      'event: agent_done',
      'data: {"type":"agent_done","agent":"FINISH"}',
      '',
      '',
    ].join('\n');
    const evts = parseSseStream(raw);
    const out = normalizeSseEvents(evts);
    const kinds = out.map((e) => e.kind);
    expect(kinds).toEqual([
      'text',
      'agent-switch',
      'approval-required',
      'agent-done',
    ]);
  });
});

// =============================================================================================
// 4) AgentExecutionGraph 嵌套 ApprovalCard 交互（HITL 闭环）
// =============================================================================================

describe('AgentExecutionGraph + HITL 嵌套', () => {
  it('节点携带 requestId 且 store 已落审批卡 → 渲染嵌套审批卡', () => {
    const sid = useChatStore.getState().activeSessionId;
    const reqId = 'req-abc-123';
    useChatStore.getState().recordApproval({
      id: reqId,
      sessionId: sid,
      toolName: 'python_interpreter',
      toolArgs: { code: 'print("hi")' },
      reason: '需要用户允许执行 Python 代码',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: '执行 python',
      requestId: reqId,
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    const approval = screen.getByTestId('agent-node-approval-card');
    expect(approval).toBeTruthy();
    expect(approval.getAttribute('data-card-status')).toBe('pending');
    expect(approval.textContent).toContain('待审批');
    expect(screen.getByTestId('agent-node-approval-args').textContent).toContain(
      'print',
    );
  });

  it('审批卡未到位时显示等待回填占位（requestId 已挂但 store 无该卡）', () => {
    const sid = useChatStore.getState().activeSessionId;
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'execute',
      requestId: 'not-yet-arrived',
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    expect(screen.getByTestId('agent-node-approval-pending')).toBeTruthy();
  });

  it('点击 "允许执行" 调用 api.chatApprove 并 resolveApproval', async () => {
    const api = (await import('@/lib/api')).api;
    const sid = useChatStore.getState().activeSessionId;
    const reqId = 'req-approve-1';
    useChatStore.getState().recordApproval({
      id: reqId,
      sessionId: sid,
      toolName: 'python_interpreter',
      toolArgs: { code: '1+1' },
      reason: 'demo',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'run',
      requestId: reqId,
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    fireEvent.click(screen.getByTestId('agent-node-approval-approve'));
    await waitFor(() => {
      expect(api.chatApprove).toHaveBeenCalledTimes(1);
    });
    expect(api.chatApprove).toHaveBeenCalledWith(
      expect.objectContaining({
        session_id: sid,
        request_id: reqId,
        tool_args: { code: '1+1' },
      }),
    );
    await waitFor(() => {
      const cards = useChatStore.getState().approvalCards[sid] ?? [];
      const card = cards.find((c) => c.id === reqId);
      expect(card?.status).toBe('approved');
    });
  });

  it('点击 "拒绝" 调用 api.chatReject 并 resolveApproval(rejected)', async () => {
    const api = (await import('@/lib/api')).api;
    const sid = useChatStore.getState().activeSessionId;
    const reqId = 'req-reject-1';
    useChatStore.getState().recordApproval({
      id: reqId,
      sessionId: sid,
      toolName: 'python_interpreter',
      toolArgs: { code: 'rm -rf /' },
      reason: 'dangerous',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'run',
      requestId: reqId,
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    fireEvent.click(screen.getByTestId('agent-node-approval-reject'));
    await waitFor(() => {
      expect(api.chatReject).toHaveBeenCalledTimes(1);
    });
    await waitFor(() => {
      const cards = useChatStore.getState().approvalCards[sid] ?? [];
      const card = cards.find((c) => c.id === reqId);
      expect(card?.status).toBe('rejected');
    });
  });

  it('点击 "编辑参数" → textarea 出现 → 输入新参数后 "用编辑后参数执行"', async () => {
    const api = (await import('@/lib/api')).api;
    const sid = useChatStore.getState().activeSessionId;
    const reqId = 'req-edit-1';
    useChatStore.getState().recordApproval({
      id: reqId,
      sessionId: sid,
      toolName: 'python_interpreter',
      toolArgs: { code: 'orig' },
      reason: 'demo',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'run',
      requestId: reqId,
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    // 进入编辑模式
    fireEvent.click(screen.getByTestId('agent-node-approval-edit-toggle'));
    const ta = screen
      .getByTestId('agent-node-approval-edit-area')
      .querySelector('textarea');
    expect(ta).toBeTruthy();
    fireEvent.change(ta as HTMLTextAreaElement, {
      target: { value: '{"code": "edited"}' },
    });
    // 此时按钮文案变成 "用编辑后参数执行"
    const btn = screen.getByTestId('agent-node-approval-approve');
    expect(btn.textContent).toContain('用编辑后参数执行');
    fireEvent.click(btn);
    await waitFor(() => {
      expect(api.chatApprove).toHaveBeenCalledWith(
        expect.objectContaining({
          request_id: reqId,
          tool_args: { code: 'edited' },
        }),
      );
    });
  });

  it('编辑模式 JSON 非法 → 给出错误提示，不调用 API', async () => {
    const api = (await import('@/lib/api')).api;
    const sid = useChatStore.getState().activeSessionId;
    const reqId = 'req-edit-bad';
    useChatStore.getState().recordApproval({
      id: reqId,
      sessionId: sid,
      toolName: 'python_interpreter',
      toolArgs: { code: 'orig' },
      reason: 'demo',
    });
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'run',
      requestId: reqId,
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    fireEvent.click(screen.getByTestId('agent-node-approval-edit-toggle'));
    const ta = screen
      .getByTestId('agent-node-approval-edit-area')
      .querySelector('textarea');
    fireEvent.change(ta as HTMLTextAreaElement, {
      target: { value: '{not valid json' },
    });
    fireEvent.click(screen.getByTestId('agent-node-approval-approve'));
    // 等待一下让 setEditError 触发
    await new Promise((r) => setTimeout(r, 30));
    expect(api.chatApprove).not.toHaveBeenCalled();
    const editArea = screen.getByTestId('agent-node-approval-edit-area');
    expect(editArea.textContent).toContain('JSON 解析失败');
  });

  it('审批卡 resolve 后不再显示按钮（仅显示状态文本）', async () => {
    const sid = useChatStore.getState().activeSessionId;
    const reqId = 'req-resolved';
    useChatStore.getState().recordApproval({
      id: reqId,
      sessionId: sid,
      toolName: 'python_interpreter',
      toolArgs: { code: '1+1' },
      reason: 'demo',
    });
    // 直接 resolve
    useChatStore.getState().resolveApproval(sid, reqId, 'approved');
    useChatStore.getState().appendAgentEvent(sid, {
      sessionId: sid,
      type: 'switch',
      agent: 'code_worker',
      reason: 'run',
      requestId: reqId,
    });
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    const approval = screen.getByTestId('agent-node-approval-card');
    expect(approval.getAttribute('data-card-status')).toBe('approved');
    // 不再有按钮
    expect(screen.queryByTestId('agent-node-approval-approve')).toBeNull();
    expect(screen.queryByTestId('agent-node-approval-reject')).toBeNull();
    expect(approval.textContent).toContain('已允许');
  });
});

// =============================================================================================
// 5) useAgentLocalRuntime 端到端（SSE → store + 消息流）
// =============================================================================================

describe('useAgentLocalRuntime: agent_switch / agent_done 落 store', () => {
  it('解析 SSE 块后 appendAgentEvent 写入 store，UI 节点链可见', () => {
    const sid = useChatStore.getState().activeSessionId;
    // 不直接调用 useAgentLocalRuntime 的 runAgentStream（其内部 fetch 需 mock）；
    // 用 sseParser + store 验证 sink 链路：
    const evts = parseSseStream(
      [
        'event: agent_switch',
        'data: {"type":"agent_switch","agent":"supervisor","reason":"go"}',
        '',
        'event: agent_switch',
        'data: {"type":"agent_switch","agent":"code_worker","reason":"run python","request_id":"r1"}',
        '',
        'event: agent_done',
        'data: {"type":"agent_done","agent":"FINISH"}',
        '',
        '',
      ].join('\n'),
    );
    const normalized = normalizeSseEvents(evts);
    // 模拟 hook 内的处理
    for (const n of normalized) {
      if (n.kind === 'agent-switch') {
        useChatStore.getState().appendAgentEvent(sid, {
          sessionId: sid,
          type: 'switch',
          agent: n.agent,
          reason: n.reason,
          requestId: n.requestId,
        });
      } else if (n.kind === 'agent-done') {
        useChatStore.getState().appendAgentEvent(sid, {
          sessionId: sid,
          type: 'done',
          agent: n.agent,
        });
      }
    }
    const events = useChatStore.getState().agentEvents[sid];
    expect(events).toHaveLength(3);
    expect(events[0].agent).toBe('supervisor');
    expect(events[1].agent).toBe('code_worker');
    expect(events[2].type).toBe('done');
    expect(events[2].agent).toBe('FINISH');

    // UI 渲染
    render(<AgentExecutionGraph sessionId={sid} defaultExpanded />);
    const nodes = screen.getAllByTestId('agent-node');
    expect(nodes.map((n) => n.getAttribute('data-agent'))).toEqual([
      'supervisor',
      'code_worker',
      'FINISH',
    ]);
  });
});