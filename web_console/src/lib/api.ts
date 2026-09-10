import type {
  Agent,
  Capability,
  CheckpointState,
  CheckpointSummary,
  ObsEvent,
  PendingApproval,
  TraceSpan,
} from '@/types/api';

// API 基础路径：
//   - 默认走同源 /api（5173 dev server 自己处理，不再代理到 8000）
//   - 如需对接独立后端，可在 .env / .env.local 设置 VITE_API_BASE=http://localhost:8000/api
const BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? '/api';

/**
 * 把后端 worker dict 规整成前端 Agent 形状。
 * 后端 WorkerProfile.to_dict() 的字段：worker_id / name / capabilities(dict) / tags / online / metrics(dict)
 * 前端 Agent：id / name / status / capabilities(string[]) / load / profile
 */
function normalizeAgent(raw: unknown): Agent {
  const r = (raw ?? {}) as Record<string, any>;
  const metrics = (r.metrics ?? {}) as Record<string, any>;
  const capDict = (r.capabilities ?? {}) as Record<string, unknown>;
  const capList = Array.isArray(r.capabilities)
    ? (r.capabilities as string[])
    : Object.keys(capDict);
  const online = r.online !== false;
  const lastStatus = String(metrics.last_status ?? '').toLowerCase();
  const status: Agent['status'] = !online
    ? 'idle'
    : lastStatus === 'busy' || (metrics.active_tasks ?? 0) > 0
      ? 'running'
      : lastStatus === 'error'
        ? 'error'
        : 'idle';
  const load = Math.max(0, Math.min(100, Number(r.load ?? metrics.load ?? 0) * 100 || 0));
  return {
    id: String(r.worker_id ?? r.id ?? ''),
    name: String(r.name ?? r.worker_id ?? 'agent'),
    status,
    capabilities: capList,
    load,
    profile: {
      ...(r.tags ? { tags: r.tags } : {}),
      ...(metrics.active_tasks !== undefined ? { active_tasks: metrics.active_tasks } : {}),
      ...(metrics.error_rate !== undefined ? { error_rate: metrics.error_rate } : {}),
      ...(metrics.recent_avg_latency_ms !== undefined
        ? { recent_avg_latency_ms: metrics.recent_avg_latency_ms }
        : {}),
    },
    currentTask:
      metrics.last_status === 'busy'
        ? `active_tasks=${metrics.active_tasks ?? 0}`
        : undefined,
  };
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    let detail = '';
    try {
      const body = await res.text();
      try {
        const parsed = JSON.parse(body);
        detail = parsed?.detail ?? parsed?.message ?? body;
      } catch {
        detail = body;
      }
    } catch {
      /* ignore */
    }
    const msg = `${res.status} ${res.statusText}${detail ? `: ${detail}` : ''}`;
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => json<{ status: string; agent_ready: boolean }>('/health'),
  agents: () =>
    json<Agent[] | { agents?: Agent[]; count?: number }>('/agents')
      .then((r) => {
        const list: unknown[] = Array.isArray(r) ? r : (r.agents ?? []);
        return list.map(normalizeAgent);
      }) as Promise<Agent[]>,
  loadStats: () => json<Record<string, unknown>>('/load_stats'),
  capabilities: () =>
    json<Capability[] | { capabilities?: Capability[]; task_types?: unknown[] }>(
      '/capabilities',
    ).then((r) => (Array.isArray(r) ? r : (r.capabilities ?? []))) as Promise<Capability[]>,
  policies: () => json<unknown[] | { policies: unknown[] }>('/policies')
    .then((r) => (Array.isArray(r) ? r : (r.policies ?? []))) as Promise<unknown[]>,

  // ----- Models / Providers -----
  models: () => json<ModelsBundle>('/models'),

  // ----- Chat 全局操作 -----
  /**
   * 清空后端 Checkpointer（即：所有 session 的对话历史）。
   * SessionSidebar / ChatPage 重置按钮使用。
   * 后端若未实现 → 抛 404；调用方需 catch 后兜底到本地清空。
   */
  clear: () => json<{ ok: boolean; cleared?: number }>('/clear', { method: 'POST' }),

  // ----- v2.2.1 — HITL 审批（per-card） -----
  /**
   * 允许一次工具调用。后端会写 HITLStore + 让模型下一轮重新调用该工具。
   * 入参与后端 HITLDecision 兼容。
   * P1-5：响应里新增 resume_url 字段，前端拿到后调用 GET /api/chat/{rid}/resume
   * 订阅续生成 SSE 流。
   */
  chatApprove: (payload: {
    session_id: string;
    request_id: string;
    tool_args?: Record<string, unknown>;
    decided_by?: string;
  }) =>
    json<{
      ok: boolean;
      request_id: string;
      decision: string;
      resume_url?: string;
    }>('/chat/approve', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  /**
   * 拒绝一次工具调用。后端会写 HITLStore + 给模型一个取消消息。
   * P1-5：响应里新增 resume_url 字段，前端拿到后调用 GET /api/chat/{rid}/resume
   * 订阅续生成 SSE 流。
   */
  chatReject: (payload: {
    session_id: string;
    request_id: string;
    reason?: string;
    decided_by?: string;
  }) =>
    json<{
      ok: boolean;
      request_id: string;
      decision: string;
      resume_url?: string;
    }>('/chat/reject', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // ----- v2.1 — Agent Presets CRUD -----
  listAgentPresets: () =>
    json<{ presets: import('@/types/api').AgentPreset[]; count?: number } | import('@/types/api').AgentPreset[]>(
      '/agents/presets',
    ).then((r) => (Array.isArray(r) ? { presets: r } : r)) as Promise<{ presets: import('@/types/api').AgentPreset[] }>,
  createAgentPreset: (
    payload: Partial<import('@/types/api').AgentPreset>,
  ) =>
    json<import('@/types/api').AgentPreset>('/agents/presets', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  updateAgentPreset: (
    id: string,
    patch: Partial<import('@/types/api').AgentPreset>,
  ) =>
    json<import('@/types/api').AgentPreset>(`/agents/presets/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: JSON.stringify(patch),
    }),
  deleteAgentPreset: (id: string) =>
    json<{ ok: boolean }>(`/agents/presets/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    }),

  /**
   * 切换主 provider/model（写到后端 in-memory 配置，立即生效）。
   * 后端路由：POST /api/model/switch，body {provider, model_name}
   */
  switchModel: (provider: string, model: string) =>
    json<{ success: boolean; message: string; provider: string; model: string }>(
      '/model/switch',
      { method: 'POST', body: JSON.stringify({ provider, model_name: model }) },
    ) as Promise<{ success: boolean; message: string; provider: string; model: string }>,

  /**
   * 测试 Provider 连通性 —— 调用后端 /api/providers/{id}/test
   * 后端若未实现此端点，返回 ok=false + reason='endpoint_not_found'，
   * 调用方 UI 应回退到"读取 /api/models 间接验证"或显示降级提示。
   */
  testConnection: async (
    provider: string,
    apiKey?: string,
    baseUrl?: string,
  ): Promise<{
    ok: boolean;
    provider: string;
    latency_ms?: number;
    message?: string;
    reason?: string;
  }> => {
    const start = performance.now();
    try {
      const r = await json<{
        ok: boolean;
        provider: string;
        latency_ms?: number;
        message?: string;
        reason?: string;
      }>(`/providers/${encodeURIComponent(provider)}/test`, {
        method: 'POST',
        body: JSON.stringify({
          api_key: apiKey ?? '',
          base_url: baseUrl ?? '',
        }),
      });
      return r;
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (/^404\b/.test(msg)) {
        return {
          ok: false,
          provider,
          reason: 'endpoint_not_found',
          message:
            '后端未实现 /api/providers/{id}/test；改用 /api/models 间接连通性检查。',
          latency_ms: performance.now() - start,
        };
      }
      return {
        ok: false,
        provider,
        reason: 'network_error',
        message: msg,
        latency_ms: performance.now() - start,
      };
    }
  },

  /**
   * 把 Provider Key / Base URL 写入后端 .env（持久化到后端进程环境）。
   * 后端若未实现 → 返回 ok=false + reason='endpoint_not_found'，UI 提示
   * 用户「请手动写入 ai_agent/.env」。
   */
  updateProviderConfig: async (
    provider: string,
    payload: { api_key?: string; base_url?: string },
  ): Promise<{
    ok: boolean;
    provider: string;
    reason?: string;
    message?: string;
  }> => {
    try {
      return await json<{
        ok: boolean;
        provider: string;
        reason?: string;
        message?: string;
      }>(`/providers/${encodeURIComponent(provider)}/config`, {
        method: 'POST',
        body: JSON.stringify(payload),
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      if (/^404\b/.test(msg)) {
        return {
          ok: false,
          provider,
          reason: 'endpoint_not_found',
          message:
            '后端未提供 /api/providers/{id}/config；请在 ai_agent/.env 中设置对应变量后重启。',
        };
      }
      return { ok: false, provider, reason: 'network_error', message: msg };
    }
  },

  events: (limit = 100) =>
    json<ObsEvent[] | { events?: ObsEvent[]; count?: number }>(`/events?limit=${limit}`)
      .then((r) => (Array.isArray(r) ? r : (r.events ?? []))) as Promise<ObsEvent[]>,
  traces: (limit = 100) =>
    json<TraceSpan[] | { traces?: TraceSpan[]; count?: number }>(`/traces?limit=${limit}`)
      .then((r) => (Array.isArray(r) ? r : (r.traces ?? []))) as Promise<TraceSpan[]>,
  metrics: () => fetch(BASE + '/metrics/prometheus').then((r) => r.text()),
  hitlPending: () =>
    json<PendingApproval[] | { pending: PendingApproval[]; count: number }>(
      '/hitl/pending',
    ).then((r) => (Array.isArray(r) ? r : (r.pending ?? []))) as Promise<PendingApproval[]>,
  hitlDecide: (id: string, decision: 'approve' | 'reject', note?: string) =>
    json<{ success: boolean; request_id: string }>('/hitl/decide', {
      method: 'POST',
      // 后端 HITLDecision 期望 request_id / status / notes；前端用 id / decision / note，做兼容映射
      body: JSON.stringify({
        request_id: id,
        status: decision === 'approve' ? 'approved' : 'rejected',
        notes: note ?? '',
        id,
        decision,
        note,
      }),
    }),
  hitlStats: () => json<unknown>('/hitl/stats'),

  // ----- v2.2.1 — HITL 审批（v2 协议）/ Checkpointer Time-Travel -----

  /**
   * v2.2.1 — 拉取某 session 的待审批清单（v2 协议）。
   * 后端路由：GET /api/hitl/v2/pending?session_id=xxx
   */
  hitlV2Pending: (sessionId: string) =>
    json<
      | PendingApproval[]
      | { pending: PendingApproval[]; count: number }
    >(`/hitl/v2/pending?session_id=${encodeURIComponent(sessionId)}`).then(
      (r) => (Array.isArray(r) ? r : (r.pending ?? [])),
    ) as Promise<PendingApproval[]>,

  /**
   * v2.2.1 — 列出某 session 的 checkpoint 历史（Time-Travel 接口基底）。
   * 后端路由：GET /api/checkpoints/list?session_id=xxx&limit=N
   */
  checkpointsList: (sessionId: string, limit = 50) =>
    json<
      | CheckpointSummary[]
      | { checkpoints: CheckpointSummary[]; count: number }
    >(
      `/checkpoints/list?session_id=${encodeURIComponent(sessionId)}&limit=${limit}`,
    ).then(
      (r) => (Array.isArray(r) ? r : (r.checkpoints ?? [])),
    ) as Promise<CheckpointSummary[]>,

  /**
   * v2.2.1 — 拉取单个 checkpoint 的完整 state 快照。
   * 后端路由：GET /api/checkpoints/get?session_id=xxx&checkpoint_id=yyy
   */
  checkpointGet: (sessionId: string, checkpointId: string) =>
    json<CheckpointState | null>(
      `/checkpoints/get?session_id=${encodeURIComponent(
        sessionId,
      )}&checkpoint_id=${encodeURIComponent(checkpointId)}`,
    ),

  // ----- Prompt 模板（System + User） -----
  promptsList: () => json<{ templates: PromptTemplateSummary[] }>('/prompts'),
  promptsRollback: (name: string, version: string) =>
    json<{ ok: boolean; name: string; version: string }>('/prompts/rollback', {
      method: 'POST',
      body: JSON.stringify({ name, version }),
    }),
  userPromptsList: () =>
    json<{ templates: PromptTemplateSummary[] }>('/user-prompts'),
  userPromptsRollback: (name: string, version: string) =>
    json<{ ok: boolean; name: string; version: string }>(
      '/user-prompts/rollback',
      { method: 'POST', body: JSON.stringify({ name, version }) },
    ),
  userPromptsRegister: (
    template: PromptTemplateDetail,
    baseName = 'default',
  ) =>
    json<{ ok: boolean; template: PromptTemplateDetail }>(
      '/user-prompts/register',
      {
        method: 'POST',
        body: JSON.stringify({ ...template, name: baseName }),
      },
    ),
  userPromptsRender: (payload: {
    name?: string;
    user_input: string;
    context?: string;
    variables?: Record<string, unknown>;
  }) =>
    json<{ ok: boolean; rendered: string; active_version?: string }>(
      '/user-prompts/render',
      { method: 'POST', body: JSON.stringify(payload) },
    ),
  userPromptsExport: () => json<unknown>('/user-prompts/export'),
  userPromptsImport: (payload: unknown) =>
    json<{ ok: boolean; imported: number }>('/user-prompts/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  // ----- Memory（对话式记忆） -----
  // 极简接口：用户输入一行文本 → 后端自动 key/value/scope，默认 scope=global
  memoryAdd: (content: string) =>
    json<{ id: number; stored: boolean; content: string; created_at?: number }>(
      '/memory/add',
      { method: 'POST', body: JSON.stringify({ content }) },
    ),
  memoryList: (limit = 100) =>
    json<{ items: MemoryItem[]; total: number }>(
      `/memory/list?limit=${limit}`,
    ),
  memoryDelete: (id: number) =>
    json<{ ok: boolean }>(`/memory/${id}`, { method: 'DELETE' }),
  memoryStats: () =>
    json<{ total: number; by_type?: Record<string, number> }>(
      '/memory/stats',
    ),

  // ----- 扩展接口（v2 widgets 使用；后端未实现时优雅降级） -----
  /**
   * 上传附件。后端未提供 /api/upload 时返回 ok=false，由调用方决定降级策略。
   */
  uploadAttachment: async (_fd: FormData): Promise<{ ok: boolean; url?: string; error?: string }> => {
    return { ok: false, error: 'uploadAttachment backend endpoint not implemented' };
  },
  /**
   * 拉取 telemetry snapshot。后端未提供 /api/telemetry/snapshot 时返回空结构。
   */
  telemetry: async (): Promise<{
    counters?: { errors_total?: number; requests_total?: number };
    gauges?: { tokens_total?: number };
    recent_spans?: Array<{ name: string; duration_ms?: number; status?: string }>;
  }> => {
    return { counters: {}, gauges: {}, recent_spans: [] };
  },
};

// ----- Prompt 相关类型 -----

// ----- Models / Providers 类型 -----
export type ProviderGroup = 'global' | 'china' | 'other';

export interface ProviderInfo {
  id: string;
  label: string;
  group: ProviderGroup;
  desc: string;
  configured: boolean;
  base_url?: string | null;
  models: string[];
  is_openai_compatible?: boolean;
}

export interface ModelsBundle {
  providers: ProviderInfo[];
  models_by_provider: Record<string, string[]>;
  current_provider: string;
  current_model: string;
  provider_meta?: Record<string, { label: string; group: ProviderGroup; desc: string }>;
}

export interface FewShotEntry {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

// ----- Memory 类型 -----
export interface MemoryItem {
  id: number;
  content: string;
  memory_type?: string;
  importance?: number;
  session_id?: string;
  created_at?: number;
  tags?: string[];
}

export interface SecurityRewritePolicy {
  enabled: boolean;
  redact_patterns: string[];
  strip_injection_markers: boolean;
  max_length: number;
}

export interface PromptTemplateDetail {
  name: string;
  version: string;
  author: string;
  changelog: string;
  // system prompt 字段（可选）
  system_block?: string;
  role_block?: string;
  tool_block_template?: string;
  cot_instructions?: string;
  // user prompt 字段（可选）
  structure?: string;
  intro_template?: string;
  few_shots?: FewShotEntry[];
  context_injection?: string;
  security_rewrite?: SecurityRewritePolicy;
  variables: string[];
  created_at: number;
}

export interface PromptTemplateSummary {
  name: string;
  active_version: string;
  versions: PromptTemplateDetail[];
}

/**
 * POST SSE 流式接口封装：使用 fetch + ReadableStream
 * 后端约定事件格式：`data: {"type":"token","content":"..."}\n\n`
 */
export interface StreamEvent {
  type:
    | 'token'
    | 'tool_call'
    | 'tool_result'
    | 'message'
    | 'done'
    | 'error'
    | 'message_start'
    | 'message_end'
    | string;
  content?: string;
  tool_call_id?: string;
  name?: string;
  args?: Record<string, unknown>;
  result?: string;
  error?: string;
}

export async function* streamChat(
  message: string,
  sessionId: string,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  const res = await fetch(BASE + '/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId }),
    signal,
  });
  if (!res.ok || !res.body) {
    yield { type: 'error', error: `HTTP ${res.status}` };
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // SSE 以 \n\n 分隔
    const parts = buffer.split('\n\n');
    buffer = parts.pop() ?? '';
    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith('data:')) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      try {
        yield JSON.parse(payload) as StreamEvent;
      } catch {
        // 忽略非 JSON 帧
      }
    }
  }
}
