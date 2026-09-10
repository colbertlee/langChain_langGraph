/**
 * credentialsStore — Settings 页面「API 供应商与密钥管理 (API Credentials)」
 *
 * 持久化策略：
 *  - 用户的 API Key / Base URL 仅存到浏览器 localStorage（按 provider_id 索引），
 *    不发送到任何远端服务器。
 *  - "发送至后端 .env" 开关开启时，把当前表单值 POST 到后端可选的
 *    /api/providers/{id}/config（后端未实现时优雅降级，弹提示）。
 *  - 启动时优先从 localStorage 取用户 key；为空则使用后端 bundle 里
 *    `configured=true` 的默认 Key（来自后端 .env）。
 *
 * 优先级（README/UI 同步说明）：
 *   1. localStorage 用户输入的 Key（最高优先级）
 *   2. 后端 .env 的默认 Key（fallback）
 *   3. 未配置（拒绝发送请求）
 */

import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

/**
 * 注意：localStorage 里仅持久化"是否有 key"以及 base_url 字段。
 * 真实 Key 在 setApiKey 时只存到内存态，组件 unmount 后立刻丢弃
 * （避免 devtools / 浏览器扩展读 localStorage 时泄露）。
 *
 * 持久化字段：
 *  - baseUrls        ：provider_id → 自定义 Base URL
 *  - sendToBackend   ：用户开关，是否把当前表单值发到后端 .env
 *  - hasKey          ：provider_id → boolean（仅记录"是否设置过"，不存值）
 */
export interface ProviderCredentialConfig {
  baseUrl?: string;
  sendToBackend?: boolean;
}

interface CredentialsState {
  /** provider_id → 自定义 Base URL（持久化） */
  baseUrls: Record<string, string>;
  /** provider_id → 是否设置过 API Key（仅布尔标记，不存值） */
  hasKey: Record<string, boolean>;
  /** 全局开关：是否把当前表单值 POST 到后端 .env */
  sendToBackend: boolean;

  // 当前正在编辑的（运行期，不持久化）：
  /** 内存态：provider_id → 真实 API Key（关闭弹窗即丢弃） */
  draftKeys: Record<string, string>;

  // actions
  setDraftKey: (providerId: string, key: string) => void;
  clearDraftKey: (providerId: string) => void;
  getDraftKey: (providerId: string) => string;
  hasDraftKey: (providerId: string) => boolean;

  setBaseUrl: (providerId: string, url: string) => void;
  setSendToBackend: (v: boolean) => void;

  /** 用户点 "保存" 时调用：把 draftKeys / baseUrls / sendToBackend 一起 commit */
  commit: (providerId: string) => void;
  /** 清除某个 provider 的全部配置（key / base_url / hasKey） */
  clearProvider: (providerId: string) => void;

  /**
   * 把最近一次成功的模型清单缓存到 localStorage（仅 provider/model 列表 + 配置位，
   * 不缓存 key），用于后端不可达时的离线降级。
   */
  cacheBundle: (bundle: unknown) => void;
  getCachedBundle: () => unknown | null;
}

const CACHE_KEY = 'agent-console-provider-cache-v1';

export const useCredentialsStore = create<CredentialsState>()(
  persist(
    (set, get) => ({
      baseUrls: {},
      hasKey: {},
      sendToBackend: false,
      draftKeys: {},

      setDraftKey: (providerId, key) =>
        set((st) => ({
          draftKeys: { ...st.draftKeys, [providerId]: key },
        })),
      clearDraftKey: (providerId) =>
        set((st) => {
          const next = { ...st.draftKeys };
          delete next[providerId];
          return { draftKeys: next };
        }),
      getDraftKey: (providerId) => get().draftKeys[providerId] ?? '',
      hasDraftKey: (providerId) => Boolean(get().draftKeys[providerId]),

      setBaseUrl: (providerId, url) =>
        set((st) => ({
          baseUrls: { ...st.baseUrls, [providerId]: url },
        })),
      setSendToBackend: (v) => set({ sendToBackend: v }),

      commit: (providerId) =>
        set((st) => {
          const draft = st.draftKeys[providerId];
          const next = {
            hasKey: { ...st.hasKey },
            draftKeys: { ...st.draftKeys },
          };
          if (draft && draft.trim().length > 0) {
            next.hasKey[providerId] = true;
            // 把 draft 移到内存态保留；关闭弹窗前不会丢失
          } else {
            next.hasKey[providerId] = false;
            delete next.draftKeys[providerId];
          }
          return next;
        }),

      clearProvider: (providerId) =>
        set((st) => {
          const baseUrls = { ...st.baseUrls };
          const hasKey = { ...st.hasKey };
          const draftKeys = { ...st.draftKeys };
          delete baseUrls[providerId];
          delete hasKey[providerId];
          delete draftKeys[providerId];
          return { baseUrls, hasKey, draftKeys };
        }),

      cacheBundle: (bundle) => {
        try {
          localStorage.setItem(CACHE_KEY, JSON.stringify(bundle));
        } catch {
          /* localStorage 满 / 禁用 —— 静默 */
        }
      },
      getCachedBundle: () => {
        try {
          const raw = localStorage.getItem(CACHE_KEY);
          if (!raw) return null;
          return JSON.parse(raw);
        } catch {
          return null;
        }
      },
    }),
    {
      name: 'agent-console-credentials',
      storage: createJSONStorage(() => localStorage),
      version: 1,
      // 仅持久化 baseUrls / hasKey / sendToBackend + 缓存的 bundle
      partialize: (s) => ({
        baseUrls: s.baseUrls,
        hasKey: s.hasKey,
        sendToBackend: s.sendToBackend,
      }),
    },
  ),
);