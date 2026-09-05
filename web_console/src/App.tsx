/**
 * v2.0 slim — App.tsx（3 页面骨架）
 *
 * 路由表：
 *   /            → ChatPage
 *   /chat        → ChatPage
 *   /admin       → AdminPage（Tab 聚合：Agents / Tools / Settings / Approval / Memory / Prompts）
 *   /insights    → InsightsPage（Token 用量 / 错误率 / Trace 列表）
 *
 * 兼容：/agents /tools /settings /approval /prompts /memory /observability
 *       均重定向到 /admin?tab=xxx 或 /insights（保持旧链接可用）。
 *
 * 旧 page 文件（Agents.tsx / Tools.tsx / ...）原样保留，未删除，
 * 由 AdminPage 的 Tabs 通过动态 import 复用，避免一次性重构破坏契约。
 */
import { useEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { ChatPage } from '@/pages/v2/ChatPage';
import { AdminPage } from '@/pages/v2/AdminPage';
import { InsightsPage } from '@/pages/v2/InsightsPage';
import { api } from '@/lib/api';
import { useUIStore } from '@/stores/uiStore';

export default function App() {
  const setBackendOnline = useUIStore((s) => s.setBackendOnline);

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

  return (
    <AppShell>
      <CompatRedirects />
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/insights" element={<InsightsPage />} />
        <Route path="*" element={<Navigate to="/chat" replace />} />
      </Routes>
    </AppShell>
  );
}

/**
 * CompatRedirects:
 * 兼容老路径（/agents /tools /settings /approval /prompts /memory /observability）
 * 通过 query 转发到 AdminPage / InsightsPage 的对应 tab。
 */
function CompatRedirects() {
  const loc = useLocation();
  const path = loc.pathname.replace(/^\//, '');
  // 仅在 path 不在 v2 路由表里时做转发
  if (['chat', 'admin', 'insights', ''].includes(path)) return null;
  if (path === 'observability') return <Navigate to={`/insights?tab=traces`} replace />;
  if (['agents', 'tools', 'settings', 'approval', 'memory', 'prompts'].includes(path)) {
    return <Navigate to={`/admin?tab=${path}`} replace />;
  }
  return null;
}