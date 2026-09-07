import { useEffect, useMemo, useState } from 'react';
import { Cpu, RefreshCw, AlertCircle, CheckCircle2, AlertTriangle, Loader2, Zap } from 'lucide-react';
import { api, type ModelsBundle, type ProviderInfo, type ProviderGroup } from '@/lib/api';
import { cn } from '@/lib/utils';

const GROUP_LABELS: Record<ProviderGroup, string> = {
  global: '🌐 全球 (Global)',
  china: '🇨🇳 国内 (China)',
  other: '📦 其他 (Other)',
};
const GROUP_ORDER: ProviderGroup[] = ['global', 'china', 'other'];
const GROUP_DESC: Record<ProviderGroup, string> = {
  global: '海外主流模型，海外节点访问',
  china: '国产模型，国内访问稳定',
  other: '开源/本地/其他服务',
};

interface SwitchResult {
  ok: boolean;
  message: string;
  provider: string;
  model: string;
}

export function Tools() {
  const [bundle, setBundle] = useState<ModelsBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [switching, setSwitching] = useState<string | null>(null);
  const [result, setResult] = useState<SwitchResult | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.models();
      setBundle(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBundle(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const switchModel = async (provider: ProviderInfo, model: string) => {
    if (!provider.configured) return;
    const key = `${provider.id}/${model}`;
    setSwitching(key);
    setResult(null);
    try {
      const r = await api.switchModel(provider.id, model);
      if (r.success) {
        setResult({
          ok: true,
          message: `✅ 已切换到 ${r.provider}/${r.model}`,
          provider: r.provider,
          model: r.model,
        });
        await load(); // 刷新 current_provider/current_model
      } else {
        setResult({
          ok: false,
          message: `❌ 切换失败：${r.message ?? '未知错误'}`,
          provider: provider.id,
          model,
        });
      }
    } catch (e) {
      setResult({
        ok: false,
        message: `❌ ${e instanceof Error ? e.message : String(e)}`,
        provider: provider.id,
        model,
      });
    } finally {
      setSwitching(null);
      setTimeout(() => setResult(null), 3500);
    }
  };

  // 按 group 分组
  const grouped = useMemo(() => {
    if (!bundle) return [];
    const map = new Map<ProviderGroup, ProviderInfo[]>();
    for (const g of GROUP_ORDER) map.set(g, []);
    for (const p of bundle.providers) {
      const g = (p.group in GROUP_LABELS ? p.group : 'other') as ProviderGroup;
      map.get(g)!.push(p);
    }
    return GROUP_ORDER.map((g) => ({
      group: g,
      items: map.get(g) || [],
    })).filter((x) => x.items.length > 0);
  }, [bundle]);

  // 统计：已配置 / 未配置
  const stats = useMemo(() => {
    if (!bundle) return { total: 0, configured: 0, models: 0 };
    let configured = 0;
    let models = 0;
    for (const p of bundle.providers) {
      if (p.configured) configured++;
      models += p.models.length;
    }
    return { total: bundle.providers.length, configured, models };
  }, [bundle]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="max-w-5xl mx-auto space-y-4">
        {/* 顶部标题 + 摘要 */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-[16px] font-semibold flex items-center gap-2">
              <Cpu className="w-4 h-4 text-accent1" />
              模型配置 & 切换
            </h2>
            <p className="text-[11.5px] text-fg2 mt-1">
              已配置 API Key 的 provider 可直接点击切换使用。对话窗口顶部会显示当前激活的模型。
            </p>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="h-8 px-2.5 text-[11.5px] rounded-full border border-[var(--border)] text-fg1 hover:text-fg0 hover-overlay flex items-center gap-1 disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3.5 h-3.5', loading && 'animate-spin')} />
            {loading ? '加载中…' : '刷新'}
          </button>
        </div>

        {/* 当前激活模型 */}
        {bundle && (
          <div className="card p-4 flex items-center gap-3">
            <div className="w-9 h-9 rounded-[10px] flex items-center justify-center bg-accent-grad shadow-glow">
              <Zap className="w-4 h-4 text-white" strokeWidth={2.2} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="text-[11px] text-fg2 uppercase tracking-wider font-mono">
                当前激活
              </div>
              <div className="text-[15px] font-semibold text-fg0 font-mono truncate">
                {bundle.current_provider}
                <span className="text-fg2 mx-1.5">/</span>
                {bundle.current_model}
              </div>
            </div>
            <div className="text-right">
              <div className="text-[11px] text-fg2">
                {stats.configured} / {stats.total} 已配置
              </div>
              <div className="text-[11px] text-fg2">
                共 {stats.models} 个模型
              </div>
            </div>
          </div>
        )}

        {/* 切换结果提示 */}
        {result && (
          <div
            className={cn(
              'p-3 rounded-[8px] border text-[12.5px] flex items-start gap-2',
              result.ok
                ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                : 'border-red-500/30 bg-red-500/10 text-red-300',
            )}
          >
            {result.ok ? (
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            )}
            <div>{result.message}</div>
          </div>
        )}

        {/* 错误 */}
        {error && (
          <div className="p-3 rounded-[8px] border border-red-500/30 bg-red-500/10 text-red-300 text-[12px] flex items-start gap-2">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
            <div>
              <div className="font-semibold">加载模型清单失败</div>
              <div className="opacity-80 mt-0.5">{error}</div>
              <div className="text-fg2 mt-1">
                请确认后端 <code className="font-mono">app.py</code> 已启动在 8000 端口。
              </div>
            </div>
          </div>
        )}

        {/* 加载中 */}
        {loading && !bundle && (
          <div className="card p-8 text-center text-[13px] text-fg2 flex items-center justify-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />
            正在加载模型清单…
          </div>
        )}

        {/* Provider 分组 */}
        {grouped.map(({ group, items }) => (
          <div key={group} className="card p-4">
            <div className="flex items-baseline justify-between mb-3">
              <h3 className="text-[13px] font-semibold text-fg0">{GROUP_LABELS[group]}</h3>
              <span className="text-[11px] text-fg2">{GROUP_DESC[group]}</span>
            </div>
            <div className="space-y-2">
              {items.map((p) => (
                <ProviderRow
                  key={p.id}
                  provider={p}
                  currentProvider={bundle?.current_provider ?? ''}
                  currentModel={bundle?.current_model ?? ''}
                  switching={switching}
                  onSwitch={(model) => switchModel(p, model)}
                />
              ))}
            </div>
          </div>
        ))}

        {/* 底部说明 */}
        {bundle && (
          <div className="text-[11px] text-fg2 px-1 leading-relaxed">
            API Key 配置位置：在 <code className="font-mono">ai_agent/.env</code> 中设置{' '}
            <code className="font-mono">{'<PROVIDER>_API_KEY'}</code> 后重启{' '}
            <code className="font-mono">app.py</code>。本页面只展示已配置的 provider，
            未配置的灰显。
          </div>
        )}
      </div>
    </div>
  );
}

// 单个 provider 行
interface ProviderRowProps {
  provider: ProviderInfo;
  currentProvider: string;
  currentModel: string;
  switching: string | null;
  onSwitch: (model: string) => void;
}

function ProviderRow({
  provider,
  currentProvider,
  currentModel,
  switching,
  onSwitch,
}: ProviderRowProps) {
  const isCurrent = provider.id === currentProvider;
  return (
    <div
      className={cn(
        'rounded-[10px] border p-3 transition-colors',
        isCurrent
          ? 'border-cyan-500/40 bg-cyan-500/5'
          : provider.configured
            ? 'border-[var(--border)] hover:border-cyan-500/25'
            : 'border-[var(--border)] opacity-60',
      )}
    >
      <div className="flex items-start gap-3">
        {/* provider 名称 + 状态 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[13px] font-semibold text-fg0 font-mono">
              {provider.label}
            </span>
            {isCurrent && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-300 font-medium flex items-center gap-1">
                <Zap className="w-2.5 h-2.5" />
                当前使用
              </span>
            )}
            {provider.configured ? (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/15 text-emerald-400 font-medium flex items-center gap-1">
                <CheckCircle2 className="w-2.5 h-2.5" />
                Key 已配置
              </span>
            ) : (
              <span
                className="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-400 font-medium flex items-center gap-1"
                title={`请在 .env 设置 ${provider.id.toUpperCase()}_API_KEY`}
              >
                <AlertTriangle className="w-2.5 h-2.5" />
                未配置
              </span>
            )}
          </div>
          {provider.desc && (
            <p className="text-[11.5px] text-fg2 mt-1 leading-relaxed">
              {provider.desc}
            </p>
          )}
          {provider.base_url && (
            <p className="text-[10.5px] text-fg2 font-mono opacity-70 mt-0.5 truncate">
              {provider.base_url}
            </p>
          )}
        </div>
      </div>

      {/* 模型 chip 列表 */}
      {provider.models.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {provider.models.map((m) => {
            const isThisCurrent = isCurrent && m === currentModel;
            const key = `${provider.id}/${m}`;
            const isSwitching = switching === key;
            const disabled = !provider.configured || isThisCurrent || isSwitching;
            return (
              <button
                key={m}
                onClick={() => onSwitch(m)}
                disabled={disabled}
                title={
                  isThisCurrent
                    ? '当前使用'
                    : provider.configured
                      ? `切换到 ${provider.label}/${m}`
                      : '未配置 API Key，无法切换'
                }
                className={cn(
                  'h-7 px-2.5 text-[11.5px] rounded-full border transition-colors flex items-center gap-1.5 font-mono',
                  isThisCurrent
                    ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-300 cursor-default'
                    : provider.configured
                      ? 'border-[var(--border)] text-fg1 hover:border-cyan-500/40 hover:text-fg0 hover-overlay'
                      : 'border-[var(--border)] text-fg2 cursor-not-allowed opacity-60',
                  isSwitching && 'opacity-70',
                )}
              >
                {isSwitching && <Loader2 className="w-3 h-3 animate-spin" />}
                {m}
                {isThisCurrent && !isSwitching && <Zap className="w-2.5 h-2.5" />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
