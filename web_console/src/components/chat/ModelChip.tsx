/**
 * ModelChip — 在对话窗口顶部显示当前激活的 provider/model。
 *
 * 数据来源：GET /api/models → current_provider + current_model
 * 交互：点击跳转 /admin?tab=tools（模型切换页）。
 *
 * 关键不变量：
 * - 与 Tools.tsx 的「当前激活」卡片数据完全一致（同源 /api/models）
 * - 切换模型时通过 /api/model/switch → 立即刷新本组件
 * - 后端不可达时不报错，只静默隐藏
 */
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Cpu, Zap, ChevronRight } from 'lucide-react';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';

interface ModelInfo {
  provider: string;
  model: string;
  configured: boolean;
}

interface ModelChipProps {
  /** 紧凑模式（用于 TopBar 右侧），省略 description */
  variant?: 'full' | 'compact';
}

export function ModelChip({ variant = 'full' }: ModelChipProps) {
  const [info, setInfo] = useState<ModelInfo | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const data = await api.models();
        if (!alive) return;
        const cur = data.providers.find((p) => p.id === data.current_provider);
        setInfo({
          provider: data.current_provider,
          model: data.current_model,
          configured: cur?.configured ?? false,
        });
      } catch {
        // 后端不可达：静默
        if (alive) setInfo(null);
      }
    };
    load();
    // 每 30s 轮询，确保切换后即时同步
    const t = setInterval(load, 30000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  const go = () => navigate('/admin?tab=tools');

  if (!info) {
    return (
      <button
        onClick={go}
        className="h-8 px-2.5 rounded-full border border-[var(--border)] text-fg2 text-[11.5px] flex items-center gap-1.5 hover-overlay"
      >
        <Cpu className="w-3.5 h-3.5" />
        <span>未连接</span>
      </button>
    );
  }

  if (variant === 'compact') {
    return (
      <button
        onClick={go}
        title={`当前：${info.provider} / ${info.model}（点击切换）`}
        className="h-8 px-2.5 rounded-full border border-[var(--border)] text-fg1 text-[11.5px] flex items-center gap-1.5 hover-overlay"
      >
        <Zap className="w-3.5 h-3.5 text-cyan-400" />
        <span className="font-mono truncate max-w-[160px]">
          {info.provider}/{info.model}
        </span>
        <ChevronRight className="w-3 h-3 text-fg2" />
      </button>
    );
  }

  // full（默认）：放在 ChatPage 顶部
  return (
    <button
      onClick={go}
      className={cn(
        'h-9 pl-2 pr-2.5 rounded-full border transition-colors flex items-center gap-2',
        info.configured
          ? 'border-[var(--border)] hover:border-cyan-500/40 hover-overlay'
          : 'border-amber-500/30 hover:border-amber-500/50',
      )}
      title={`当前使用：${info.provider} / ${info.model}（点击切换）`}
    >
      <div
        className={cn(
          'w-6 h-6 rounded-full flex items-center justify-center shrink-0',
          info.configured ? 'bg-accent-grad shadow-glow' : 'bg-amber-500/20',
        )}
      >
        <Zap
          className={cn(
            'w-3 h-3',
            info.configured ? 'text-white' : 'text-amber-400',
          )}
          strokeWidth={2.4}
        />
      </div>
      <div className="flex flex-col items-start leading-none gap-0.5">
        <span className="text-[9px] uppercase tracking-wider text-fg2 font-mono">
          当前模型
        </span>
        <span className="text-[12px] font-semibold text-fg0 font-mono truncate max-w-[200px]">
          {info.provider}
          <span className="text-fg2 mx-1">/</span>
          {info.model}
        </span>
      </div>
      <ChevronRight className="w-3.5 h-3.5 text-fg2 ml-0.5" />
    </button>
  );
}
