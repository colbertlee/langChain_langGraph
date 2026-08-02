import { useEffect } from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { Chat } from '@/pages/Chat';
import { Agents } from '@/pages/Agents';
import { Approval } from '@/pages/Approval';
import { Observability } from '@/pages/Observability';
import { Tools } from '@/pages/Tools';
import { Settings } from '@/pages/Settings';
import { Prompts } from '@/pages/Prompts';
import { Memory } from '@/pages/Memory';
import { api } from '@/lib/api';
import { useUIStore } from '@/stores/uiStore';

export default function App() {
  const setBackendOnline = useUIStore((s) => s.setBackendOnline);
  const setMcpSummary = useUIStore((s) => s.setMcpSummary);

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        await api.health();
        if (!cancelled) setBackendOnline(true);
      } catch {
        if (!cancelled) setBackendOnline(false);
      }
    };
    check();
    const t = window.setInterval(check, 8000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [setBackendOnline]);

  // 周期刷新 MCP 摘要,给 Sidebar 角标用
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const r = await api.mcpServers();
        const tools = await api.mcpTools().catch(() => ({ tools: [] }));
        if (cancelled) return;
        const running = (r.servers || []).filter((s) => s.running).length;
        setMcpSummary(running, (tools.tools || []).length);
      } catch {
        // 后端未启 / 接口未就绪时静默忽略
      }
    };
    refresh();
    const t = window.setInterval(refresh, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, [setMcpSummary]);

  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<Chat />} />
        <Route path="/agents" element={<Agents />} />
        <Route path="/approval" element={<Approval />} />
        <Route path="/observability" element={<Observability />} />
        <Route path="/tools" element={<Tools />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/prompts" element={<Prompts />} />
        <Route path="/memory" element={<Memory />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}
