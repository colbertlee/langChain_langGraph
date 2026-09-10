/**
 * v2.1 — agentStore 单测
 *
 * 覆盖：
 *  - 默认状态
 *  - loadPresets 从 mock api 加载 + 失败回退
 *  - bindAgentToSession / unbindAgentFromSession
 *  - resolveActiveAgentId 优先级
 *  - createPreset / updatePreset / deletePreset 同步本地状态
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { useAgentStore, _agentStoreTestHelpers } from './agentStore';

// mock api
vi.mock('@/lib/api', () => {
  const presets = [
    {
      id: 'builtin-general',
      name: '通用助手',
      description: '通用',
      avatar: '🤖',
      system_prompt: '通用提示',
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
      system_prompt: '重构提示',
      temperature: 0.3,
      tools: ['python_exec'],
      builtin: true,
      created_at: 2,
      updated_at: 2,
    },
  ];
  return {
    api: {
      listAgentPresets: vi.fn(async () => ({ presets, count: presets.length })),
      createAgentPreset: vi.fn(async (payload: any) => ({
        id: `u-${Math.random().toString(16).slice(2, 8)}`,
        ...payload,
        builtin: false,
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
      })),
      updateAgentPreset: vi.fn(async (id: string, patch: any) => ({
        id,
        ...patch,
        updated_at: Date.now() / 1000,
      })),
      deleteAgentPreset: vi.fn(async (id: string) => ({ deleted: id })),
    },
  };
});

describe('agentStore', () => {
  beforeEach(() => {
    useAgentStore.getState().resetForTests();
  });

  it('初始默认值', () => {
    const s = useAgentStore.getState();
    expect(s.presets).toEqual([]);
    expect(s.defaultAgentId).toBe('builtin-general');
    expect(s.sessionAgentMap).toEqual({});
    expect(s.loading).toBe(false);
    expect(s.loaded).toBe(false);
  });

  it('loadPresets 成功后填入 presets', async () => {
    const { api } = await import('@/lib/api');
    await useAgentStore.getState().loadPresets();
    const s = useAgentStore.getState();
    expect(s.presets.length).toBe(2);
    expect(s.loaded).toBe(true);
    expect(api.listAgentPresets).toHaveBeenCalledTimes(1);
  });

  it('loadPresets 失败时不抛错，presets 保持空', async () => {
    const { api } = await import('@/lib/api');
    vi.mocked(api.listAgentPresets).mockRejectedValueOnce(new Error('boom'));
    await useAgentStore.getState().loadPresets();
    expect(useAgentStore.getState().presets).toEqual([]);
    expect(useAgentStore.getState().loaded).toBe(false);
  });

  it('defaultAgentId 失效时回退到第一个 builtin', async () => {
    useAgentStore.setState({ defaultAgentId: 'ghost-id' });
    await useAgentStore.getState().loadPresets();
    expect(useAgentStore.getState().defaultAgentId).toBe('builtin-general');
  });

  it('bindAgentToSession / unbindAgentFromSession', () => {
    useAgentStore.getState().bindAgentToSession('s1', 'builtin-refactor');
    expect(useAgentStore.getState().sessionAgentMap.s1).toBe('builtin-refactor');
    useAgentStore.getState().unbindAgentFromSession('s1');
    expect(useAgentStore.getState().sessionAgentMap.s1).toBeUndefined();
  });

  it('resolveActiveAgentId 优先级：sessionAgentMap > defaultAgentId', () => {
    useAgentStore.setState({
      defaultAgentId: 'builtin-general',
      sessionAgentMap: { s2: 'builtin-refactor' },
    });
    expect(useAgentStore.getState().resolveActiveAgentId('s1')).toBe('builtin-general');
    expect(useAgentStore.getState().resolveActiveAgentId('s2')).toBe('builtin-refactor');
  });

  it('createPreset 追加到头部', async () => {
    useAgentStore.setState({ presets: [{ id: 'a', name: 'A' } as any] });
    const created = await useAgentStore.getState().createPreset({ name: 'New' });
    expect(created.name).toBe('New');
    const s = useAgentStore.getState();
    expect(s.presets[0].id).toBe(created.id);
    expect(s.presets.length).toBe(2);
  });

  it('updatePreset 替换对应项', async () => {
    useAgentStore.setState({
      presets: [
        { id: 'a', name: 'Old', temperature: 0.5 } as any,
        { id: 'b', name: 'B', temperature: 0.6 } as any,
      ],
    });
    await useAgentStore.getState().updatePreset('a', { name: 'New', temperature: 0.9 });
    const s = useAgentStore.getState();
    const a = s.presets.find((p) => p.id === 'a')!;
    expect(a.name).toBe('New');
    expect(a.temperature).toBe(0.9);
    expect(s.presets.length).toBe(2);
  });

  it('deletePreset 移除项 + 若删的是 defaultAgentId 回退到 builtin-general', async () => {
    useAgentStore.setState({
      defaultAgentId: 'a',
      sessionAgentMap: { s1: 'a' },
      presets: [
        { id: 'a', name: 'A' } as any,
        { id: 'b', name: 'B' } as any,
      ],
    });
    await useAgentStore.getState().deletePreset('a');
    const s = useAgentStore.getState();
    expect(s.presets.map((p) => p.id)).toEqual(['b']);
    expect(s.defaultAgentId).toBe('builtin-general');
    expect(s.sessionAgentMap.s1).toBeUndefined();
  });

  it('resetForTests 还原初始状态', () => {
    useAgentStore.setState({
      presets: [{ id: 'x' } as any],
      defaultAgentId: 'x',
      sessionAgentMap: { s: 'x' },
    });
    useAgentStore.getState().resetForTests();
    // 只断言 data 字段；store 永远含 action 引用
    const s = useAgentStore.getState();
    expect(s.presets).toEqual([]);
    expect(s.defaultAgentId).toBe('builtin-general');
    expect(s.sessionAgentMap).toEqual({});
    expect(s.loading).toBe(false);
    expect(s.loaded).toBe(false);
  });
});
