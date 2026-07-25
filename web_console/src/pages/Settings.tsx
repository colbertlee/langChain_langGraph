import { useEffect, useMemo, useState } from 'react';
import { Key, Cpu, Save, Check, RefreshCw, AlertCircle } from 'lucide-react';
import { api, type ModelsBundle, type ProviderInfo, type ProviderGroup } from '@/lib/api';

const GROUP_LABELS: Record<ProviderGroup, string> = {
  global: '🌐 全球 (Global)',
  china: '🇨🇳 国内 (China)',
  other: '📦 其他 (Other)',
};
const GROUP_ORDER: ProviderGroup[] = ['global', 'china', 'other'];

export function Settings() {
  const [bundle, setBundle] = useState<ModelsBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // 从 localStorage 读取上次选择作为初值；若没有则用后端 current
  const [provider, setProvider] = useState<string>('');
  const [model, setModel] = useState<string>('');
  const [apiKey, setApiKey] = useState('');
  const [saved, setSaved] = useState(false);

  const loadModels = async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await api.models();
      setBundle(data);
      // 初次进入：优先用 localStorage，其次用后端 current
      const savedProv = localStorage.getItem('agent.provider');
      const savedModel = localStorage.getItem('agent.model');
      const targetProv =
        savedProv && data.providers.some((p) => p.id === savedProv)
          ? savedProv
          : data.current_provider || data.providers[0]?.id || '';
      setProvider(targetProv);
      const targetModel =
        savedModel &&
        data.providers.find((p) => p.id === targetProv)?.models.includes(savedModel)
          ? savedModel
          : data.current_model ||
            data.providers.find((p) => p.id === targetProv)?.models[0] ||
            '';
      setModel(targetModel);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setLoadError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadModels();
  }, []);

  // 按 group 分组并保持原始顺序
  const grouped = useMemo(() => {
    if (!bundle) return [];
    const map = new Map<ProviderGroup, ProviderInfo[]>();
    for (const g of GROUP_ORDER) map.set(g, []);
    for (const p of bundle.providers) {
      const g = (p.group in GROUP_LABELS ? p.group : 'other') as ProviderGroup;
      map.get(g)!.push(p);
    }
    return GROUP_ORDER.map((g) => ({ group: g, items: map.get(g) || [] })).filter(
      (x) => x.items.length > 0,
    );
  }, [bundle]);

  const cur = bundle?.providers.find((p) => p.id === provider);
  const curModels = cur?.models ?? [];

  const switchProvider = (next: string) => {
    setProvider(next);
    const p = bundle?.providers.find((x) => x.id === next);
    setModel(p?.models[0] ?? '');
  };

  const save = () => {
    localStorage.setItem('agent.provider', provider);
    localStorage.setItem('agent.model', model);
    if (apiKey) localStorage.setItem('agent.apiKey', '***masked***');
    setSaved(true);
    setTimeout(() => setSaved(false), 1600);
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-3xl mx-auto space-y-4 stagger">
        <div className="card p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Cpu className="w-4 h-4 text-accent1" />
              <h2 className="text-[15px] font-semibold">Provider & Model</h2>
            </div>
            <button
              onClick={loadModels}
              disabled={loading}
              className="text-[11.5px] text-fg2 hover:text-fg1 flex items-center gap-1 disabled:opacity-50"
              title="从后端刷新模型清单"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
              {loading ? '加载中…' : '刷新'}
            </button>
          </div>

          {loadError && (
            <div className="mb-3 p-3 rounded-[8px] border border-red-500/30 bg-red-500/10 text-red-300 text-[12px] flex items-start gap-2">
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
              <div>
                加载模型清单失败：{loadError}
                <br />
                <span className="text-fg2">
                  请确认后端 <code className="font-mono">app.py</code> 已启动（默认 8000）。
                </span>
              </div>
            </div>
          )}

          {loading && !bundle && (
            <div className="text-[12.5px] text-fg2 py-4 text-center">正在加载模型清单…</div>
          )}

          {bundle && (
            <div className="space-y-4">
              {/* Provider 分组 */}
              {grouped.map(({ group, items }) => (
                <div key={group}>
                  <label className="text-[11px] uppercase tracking-wider text-fg2 font-mono block mb-2">
                    {GROUP_LABELS[group]}
                  </label>
                  <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                    {items.map((p) => {
                      const active = provider === p.id;
                      const configured = p.configured;
                      return (
                        <button
                          key={p.id}
                          onClick={() => switchProvider(p.id)}
                          title={
                            configured
                              ? `${p.label} · ${p.desc || ''}`
                              : `${p.label} · ⚠️ 未配置 API Key（点击仍可选择，需在 .env 设置 ${p.id.toUpperCase()}_API_KEY）`
                          }
                          className={`h-10 px-3 rounded-[10px] border text-[12.5px] font-medium transition-colors flex items-center justify-center gap-1.5 ${
                            active
                              ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300'
                              : configured
                                ? 'border-[var(--border)] text-fg1 hover:bg-white/5'
                                : 'border-[var(--border)] text-fg2 hover:bg-white/5 opacity-70'
                          }`}
                        >
                          <span>{p.label}</span>
                          {!configured && (
                            <span
                              className="text-[10px] px-1 py-0.5 rounded bg-amber-500/15 text-amber-400"
                              title="未配置 API Key"
                            >
                              ⚠
                            </span>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}

              {/* 当前 provider 描述 */}
              {cur && (
                <div className="text-[11.5px] text-fg2 px-1">
                  <span className="font-mono">{cur.id}</span>
                  {cur.desc ? ` · ${cur.desc}` : ''}
                  {cur.base_url ? (
                    <>
                      {' · '}
                      <span className="font-mono opacity-70">{cur.base_url}</span>
                    </>
                  ) : null}
                </div>
              )}

              {/* Model 下拉 */}
              <div>
                <label className="text-[11px] uppercase tracking-wider text-fg2 font-mono block mb-1.5">
                  Model
                </label>
                {curModels.length > 0 ? (
                  <select
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    className="w-full h-10 px-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[10px] text-[13px] text-fg0 outline-none focus:border-cyan-500/40"
                  >
                    {curModels.map((m) => (
                      <option key={m} value={m}>
                        {m}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="text-[12px] text-fg2 italic">该 provider 没有可用模型</div>
                )}
              </div>

              {/* 汇总信息 */}
              <div className="text-[11px] text-fg2 pt-2 border-t border-[var(--border)]">
                共 {bundle.providers.length} 个 provider、{' '}
                {bundle.providers.reduce((s, p) => s + p.models.length, 0)} 个模型。
                {' '}当前后端默认：<span className="font-mono">{bundle.current_provider}</span> /{' '}
                <span className="font-mono">{bundle.current_model}</span>
              </div>
            </div>
          )}
        </div>

        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <Key className="w-4 h-4 text-accent1" />
            <h2 className="text-[15px] font-semibold">API Key</h2>
          </div>
          <input
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="sk-...（仅作占位，真实 Key 请配置后端 .env）"
            className="w-full h-10 px-3 bg-[var(--bg-1)] border border-[var(--border)] rounded-[10px] text-[13px] text-fg0 font-mono outline-none focus:border-cyan-500/40 placeholder:text-fg2"
          />
          <p className="text-[11.5px] text-fg2 mt-2">
            Key 仅存储在本地浏览器（localStorage），不会上传。
            <br />
            <span className="opacity-70">
              实际生效位置：在 ai_agent/.env 中设置 <code className="font-mono">{'<PROVIDER>_API_KEY'}</code> 后重启 app.py。
            </span>
          </p>
        </div>

        <button onClick={save} className="btn-primary h-10 px-5" disabled={!provider || !model}>
          {saved ? <Check className="w-4 h-4" /> : <Save className="w-4 h-4" />}
          {saved ? '已保存' : '保存设置'}
        </button>
      </div>
    </div>
  );
}