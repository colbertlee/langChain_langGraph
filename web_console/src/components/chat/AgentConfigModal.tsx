/**
 * AgentConfigModal — v2.1 Agent 预设编辑弹窗
 *
 * 功能：
 *  - 列表展示全部 presets（含 builtin）
 *  - 选中一个 → 编辑 system_prompt / temperature / tools（多选）
 *  - "新建" 按钮：清空表单，新建 preset
 *  - "保存" 调 api.updateAgentPreset / createAgentPreset
 *  - "删除" 调 api.deleteAgentPreset（builtin 隐藏该按钮）
 *  - Esc 关闭；点击遮罩关闭；Enter 保存
 */
import { useEffect, useMemo, useState, type FC, type KeyboardEvent } from 'react';
import { X, Save, Trash2, Plus, AlertTriangle, Bot } from 'lucide-react';
import { useAgentStore } from '@/stores/agentStore';
import { api } from '@/lib/api';
import { cn } from '@/lib/utils';
import type { AgentPreset } from '@/types/api';

interface AgentConfigModalProps {
  /** 不传则默认新建模式 */
  initialPresetId?: string;
  onClose: () => void;
  /** 切换 / 保存后回调；让 Sidebar 同步刷新 */
  onChanged?: () => void;
}

// 已知工具名（与后端 tools_v2 / tools.py / tools/search_tool / tools/code_interpreter 对齐）
const KNOWN_TOOLS = [
  { id: 'python_exec', label: 'Python 执行（同步）' },
  { id: 'python_interpreter', label: 'Python 沙箱（v2.1）' },
  { id: 'web_search', label: '联网搜索（v2.1）' },
  { id: 'code_review', label: '代码审查' },
  { id: 'file_io', label: '文件读写' },
  { id: 'web_fetch', label: '网页抓取' },
  { id: 'rag_search', label: 'RAG 检索' },
];

export const AgentConfigModal: FC<AgentConfigModalProps> = ({
  initialPresetId,
  onClose,
  onChanged,
}) => {
  const presets = useAgentStore((s) => s.presets);
  const createPreset = useAgentStore((s) => s.createPreset);
  const updatePreset = useAgentStore((s) => s.updatePreset);
  const deletePreset = useAgentStore((s) => s.deletePreset);

  // 选中的 preset id（'__new__' 表示新建）
  const [selectedId, setSelectedId] = useState<string>(
    initialPresetId ?? '__new__',
  );
  const selectedPreset = useMemo(
    () => presets.find((p) => p.id === selectedId),
    [presets, selectedId],
  );

  // 编辑表单（独立于 presets 以支持新建时的临时态）
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [avatar, setAvatar] = useState('🤖');
  const [systemPrompt, setSystemPrompt] = useState('');
  const [temperature, setTemperature] = useState(0.7);
  const [tools, setTools] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState<'save' | 'delete' | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 选中切换 → 把表单填上对应 preset 的当前值
  useEffect(() => {
    if (selectedId === '__new__') {
      setName('');
      setDescription('');
      setAvatar('🤖');
      setSystemPrompt('');
      setTemperature(0.7);
      setTools([]);
    } else if (selectedPreset) {
      setName(selectedPreset.name);
      setDescription(selectedPreset.description ?? '');
      setAvatar(selectedPreset.avatar || '🤖');
      setSystemPrompt(selectedPreset.system_prompt);
      setTemperature(selectedPreset.temperature);
      setTools([...selectedPreset.tools]);
    }
    setError(null);
    setConfirmDelete(false);
  }, [selectedId, selectedPreset]);

  const isBuiltin = selectedPreset?.builtin ?? false;

  const toggleTool = (toolId: string) => {
    setTools((prev) =>
      prev.includes(toolId) ? prev.filter((t) => t !== toolId) : [...prev, toolId],
    );
  };

  const handleSave = async () => {
    setError(null);
    if (!name.trim()) {
      setError('名称不能为空');
      return;
    }
    if (!(temperature >= 0 && temperature <= 2)) {
      setError('Temperature 必须在 [0.0, 2.0]');
      return;
    }
    setBusy('save');
    try {
      const payload = {
        name: name.trim(),
        description: description.trim(),
        avatar: avatar || '🤖',
        system_prompt: systemPrompt,
        temperature,
        tools,
      };
      if (selectedId === '__new__') {
        await createPreset(payload);
      } else if (selectedPreset) {
        await updatePreset(selectedPreset.id, payload);
      }
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const handleDelete = async () => {
    if (!selectedPreset) return;
    setBusy('delete');
    try {
      await deletePreset(selectedPreset.id);
      setSelectedId('__new__');
      onChanged?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
      setConfirmDelete(false);
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') onClose();
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSave();
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Agent 预设配置"
      data-testid="agent-config-modal"
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/55 backdrop-blur-sm px-4 py-6"
      onClick={onClose}
      onKeyDown={handleKeyDown}
    >
      <div
        className="w-full max-w-4xl max-h-full bg-[var(--bg-1)] border border-[var(--border)] rounded-xl shadow-2xl flex flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-5 py-3 border-b border-[var(--border)] flex items-center gap-2">
          <Bot className="w-4 h-4 text-accent1" />
          <h3 className="text-[14px] font-semibold text-fg0 flex-1">Agent 预设</h3>
          <span className="text-[10.5px] text-fg2 font-mono">
            Ctrl+Enter 保存 · Esc 关闭
          </span>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="w-7 h-7 rounded-md flex items-center justify-center text-fg2 hover:text-fg0 hover-overlay"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-hidden grid grid-cols-[220px_1fr]">
          {/* Left: preset list */}
          <div
            className="border-r border-[var(--border)] overflow-y-auto py-2"
            data-testid="agent-preset-list"
          >
            <button
              type="button"
              data-testid="agent-preset-new"
              data-selected={selectedId === '__new__' ? 'true' : 'false'}
              onClick={() => setSelectedId('__new__')}
              className={cn(
                'w-full text-left px-3 py-2 flex items-center gap-2 text-[12px] hover:bg-[var(--bg-2)] transition-colors',
                selectedId === '__new__' && 'bg-cyan-500/10 text-cyan-300',
              )}
            >
              <Plus className="w-3.5 h-3.5" />
              <span>新建预设</span>
            </button>
            <div className="my-1 mx-2 border-t border-[var(--border)]" />
            {presets.map((p) => (
              <button
                key={p.id}
                type="button"
                data-testid="agent-preset-item"
                data-preset-id={p.id}
                data-selected={selectedId === p.id ? 'true' : 'false'}
                onClick={() => setSelectedId(p.id)}
                className={cn(
                  'w-full text-left px-3 py-2 flex items-center gap-2 text-[12px] hover:bg-[var(--bg-2)] transition-colors',
                  selectedId === p.id && 'bg-cyan-500/10 text-cyan-300',
                )}
              >
                <span className="text-base shrink-0">{p.avatar || '🤖'}</span>
                <div className="flex-1 min-w-0">
                  <div className="truncate font-medium text-fg0">{p.name}</div>
                  <div className="text-[10px] text-fg2 truncate flex items-center gap-1">
                    {p.builtin && (
                      <span className="px-1 rounded bg-amber-500/15 text-amber-300">
                        内置
                      </span>
                    )}
                    <span>T={p.temperature.toFixed(1)}</span>
                    {p.tools.length > 0 && <span>· {p.tools.length} tools</span>}
                  </div>
                </div>
              </button>
            ))}
          </div>

          {/* Right: edit form */}
          <div className="overflow-y-auto p-5 space-y-4">
            {error && (
              <div
                data-testid="agent-config-error"
                className="px-3 py-2 rounded-md bg-rose-500/10 border border-rose-500/30 text-rose-200 text-[12px] flex items-center gap-2"
              >
                <AlertTriangle className="w-3.5 h-3.5" />
                {error}
              </div>
            )}

            <div className="grid grid-cols-[60px_1fr] gap-3 items-center">
              <label className="text-[11.5px] text-fg1">头像</label>
              <input
                type="text"
                data-testid="agent-avatar-input"
                value={avatar}
                onChange={(e) => setAvatar(e.target.value)}
                disabled={isBuiltin}
                maxLength={4}
                className="w-14 h-9 px-2 text-center text-[18px] bg-[var(--bg-0)] border border-[var(--border)] rounded text-fg0 outline-none focus:border-cyan-500/50 disabled:opacity-50"
              />

              <label className="text-[11.5px] text-fg1">名称 *</label>
              <input
                type="text"
                data-testid="agent-name-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                disabled={isBuiltin}
                placeholder="如：我的客服"
                className="h-9 px-3 bg-[var(--bg-0)] border border-[var(--border)] rounded text-[13px] text-fg0 outline-none focus:border-cyan-500/50 disabled:opacity-50"
                maxLength={40}
              />

              <label className="text-[11.5px] text-fg1">说明</label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="简短描述这个 Agent 的用途"
                className="h-9 px-3 bg-[var(--bg-0)] border border-[var(--border)] rounded text-[13px] text-fg0 outline-none focus:border-cyan-500/50"
                maxLength={120}
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[11.5px] text-fg1">System Prompt</label>
                <span className="text-[10px] text-fg2 font-mono">
                  {systemPrompt.length} 字符
                </span>
              </div>
              <textarea
                data-testid="agent-system-prompt-input"
                value={systemPrompt}
                onChange={(e) => setSystemPrompt(e.target.value)}
                rows={6}
                placeholder="例如：你是一名专业的数据分析师..."
                className="w-full px-3 py-2 bg-[var(--bg-0)] border border-[var(--border)] rounded text-[12.5px] font-mono text-fg0 outline-none focus:border-cyan-500/50 resize-y"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-[11.5px] text-fg1">Temperature</label>
                <span
                  data-testid="agent-temperature-value"
                  className="text-[12px] font-mono text-cyan-300"
                >
                  {temperature.toFixed(2)}
                </span>
              </div>
              <input
                type="range"
                data-testid="agent-temperature-slider"
                min={0}
                max={2}
                step={0.05}
                value={temperature}
                onChange={(e) => setTemperature(parseFloat(e.target.value))}
                className="w-full accent-cyan-400"
              />
              <div className="flex justify-between text-[10px] text-fg2 mt-1 font-mono">
                <span>0.0 精确</span>
                <span>0.7 平衡</span>
                <span>1.5 创意</span>
                <span>2.0 随机</span>
              </div>
            </div>

            <div>
              <label className="text-[11.5px] text-fg1 mb-1.5 block">Tools</label>
              <div className="grid grid-cols-2 gap-2" data-testid="agent-tools-grid">
                {KNOWN_TOOLS.map((t) => {
                  const checked = tools.includes(t.id);
                  const isV21 = t.id === 'web_search' || t.id === 'python_interpreter';
                  return (
                    <label
                      key={t.id}
                      className={cn(
                        'flex items-center gap-2 px-2.5 py-1.5 rounded-md border cursor-pointer text-[12px] transition-colors',
                        checked
                          ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                          : 'border-[var(--border)] hover:bg-[var(--bg-2)] text-fg1',
                      )}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleTool(t.id)}
                        data-testid={`agent-tool-${t.id}`}
                        className="accent-cyan-400"
                      />
                      <span className="font-mono text-[10.5px] text-fg2">{t.id}</span>
                      <span className="flex-1 truncate">{t.label}</span>
                      {isV21 && (
                        <span className="px-1 rounded bg-emerald-500/15 text-emerald-300 text-[9.5px]">
                          v2.1
                        </span>
                      )}
                    </label>
                  );
                })}
              </div>
              {tools.filter((t) => !KNOWN_TOOLS.some((k) => k.id === t)).length > 0 && (
                <div className="mt-2 text-[10.5px] text-amber-300">
                  含未在已知列表中的工具：{tools.filter((t) => !KNOWN_TOOLS.some((k) => k.id === t)).join(', ')}
                </div>
              )}
            </div>

            {isBuiltin && (
              <div className="px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-200 text-[11.5px] flex items-center gap-2">
                <AlertTriangle className="w-3.5 h-3.5" />
                系统内置预设不可删除，可调整 system_prompt 和 temperature 后保存（会复制一份新预设）。
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-[var(--border)] flex items-center justify-between gap-2">
          <div>
            {selectedPreset && !selectedPreset.builtin && !confirmDelete && (
              <button
                type="button"
                data-testid="agent-delete-btn"
                onClick={() => setConfirmDelete(true)}
                className="h-8 px-3 text-[12px] rounded-md border border-rose-500/40 text-rose-300 hover:bg-rose-500/10 flex items-center gap-1.5"
              >
                <Trash2 className="w-3.5 h-3.5" />
                删除
              </button>
            )}
            {confirmDelete && (
              <div className="flex items-center gap-2">
                <span className="text-[12px] text-rose-300">确定删除？</span>
                <button
                  type="button"
                  data-testid="agent-delete-confirm"
                  onClick={handleDelete}
                  disabled={busy !== null}
                  className="h-8 px-3 text-[12px] rounded-md bg-rose-500/30 text-rose-100 hover:bg-rose-500/40 disabled:opacity-50"
                >
                  是的，删除
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmDelete(false)}
                  className="h-8 px-3 text-[12px] rounded-md border border-[var(--border)] text-fg1 hover:text-fg0"
                >
                  取消
                </button>
              </div>
            )}
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="h-8 px-3 text-[12px] rounded-md border border-[var(--border)] text-fg1 hover:text-fg0 hover-overlay"
            >
              取消
            </button>
            <button
              type="button"
              data-testid="agent-save-btn"
              onClick={handleSave}
              disabled={busy !== null}
              className="h-8 px-4 text-[12px] rounded-md bg-accent-grad text-white shadow-glow hover:brightness-110 flex items-center gap-1.5 disabled:opacity-50"
            >
              <Save className="w-3.5 h-3.5" />
              保存
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

// Helper for tests
export const _agentConfigModalTestHelpers = {
  KNOWN_TOOLS,
};
