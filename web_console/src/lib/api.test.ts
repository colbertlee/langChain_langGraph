import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from './api';

describe('api helpers', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('health', async () => {
    global.fetch = vi.fn(async () =>
      ({ ok: true, status: 200, json: async () => ({ status: 'ok', agent_ready: true }) }) as Response,
    ) as unknown as typeof fetch;
    const r = await api.health();
    expect(r.status).toBe('ok');
  });

  it('agents', async () => {
    global.fetch = vi.fn(async () =>
      ({ ok: true, status: 200, json: async () => [{ id: 'a', name: 'a', status: 'idle', capabilities: [], load: 0 }] }) as Response,
    ) as unknown as typeof fetch;
    const r = await api.agents();
    expect(r[0].id).toBe('a');
  });

  it('hitlDecide', async () => {
    global.fetch = vi.fn(async () =>
      ({ ok: true, status: 200, json: async () => ({ ok: true }) }) as Response,
    ) as unknown as typeof fetch;
    const r = await api.hitlDecide('req-1', 'approve');
    expect(r.ok).toBe(true);
  });

  it('throws on non-2xx', async () => {
    global.fetch = vi.fn(async () =>
      ({ ok: false, status: 500, statusText: 'Server Error', json: async () => ({}) }) as Response,
    ) as unknown as typeof fetch;
    await expect(api.health()).rejects.toThrow(/500/);
  });
});