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
import { ThemeSync } from '@/components/layout/ThemeSync';
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
      <ThemeSync />
      <CompatRedirects />
      <Routes>
        <Route path="/" element={<Navigate to="/chat" replace />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/insights" element={<InsightsPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </AppShell>
  );
}

function NotFound() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-6">
      <div className="text-6xl font-bold text-fg2 mb-3">404</div>
      <div className="text-lg text-fg1 mb-2">页面不存在</div>
      <a href="/chat" className="btn-primary mt-4">返回 Chat</a>
    </div>
  );
}

/**
 * 兼容旧链接：将 /agents /tools /settings /approval /prompts /memory /observability
 * 重定向到新路由，并保留 search 状态。
 */
function CompatRedirects() {
  const loc = useLocation();
  const map: Record<string, string> = {
    '/agents': '/admin?tab=agents',
    '/tools': '/admin?tab=tools',
    '/settings': '/admin?tab=settings',
    '/approval': '/admin?tab=approval',
    '/prompts': '/admin?tab=prompts',
    '/memory': '/admin?tab=memory',
    '/observability': '/insights',
  };
  const target = map[loc.pathname];
  if (target) {
    return <Navigate to={target} replace />;
  }
  return null;
}
