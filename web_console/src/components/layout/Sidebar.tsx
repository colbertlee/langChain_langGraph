import { NavLink } from 'react-router-dom';
import {
  MessageSquare,
  Bot,
  ShieldCheck,
  Activity,
  Wrench,
  Settings as Cog,
  PanelLeftClose,
  PanelLeftOpen,
  Sparkles,
  Beaker,
  Brain,
} from 'lucide-react';
import { useUIStore } from '@/stores/uiStore';
import { cn } from '@/lib/utils';

const items = [
  { to: '/', label: 'Chat', icon: MessageSquare },
  { to: '/agents', label: 'Agents', icon: Bot },
  { to: '/approval', label: 'Approval', icon: ShieldCheck },
  { to: '/observability', label: 'Observability', icon: Activity },
  { to: '/tools', label: 'Tools', icon: Wrench },
  { to: '/settings', label: 'Settings', icon: Cog },
  { to: '/prompts', label: 'Prompts', icon: Beaker },
  { to: '/memory', label: 'Memory', icon: Brain },
];

export function Sidebar() {
  const collapsed = useUIStore((s) => s.sidebarCollapsed);
  const toggle = useUIStore((s) => s.toggleSidebar);
  const online = useUIStore((s) => s.backendOnline);

  return (
    <aside
      className="fixed inset-y-0 left-0 z-30 flex flex-col border-r border-[var(--border)] bg-[rgba(10,10,11,0.78)] backdrop-blur-xl transition-[width] duration-300"
      style={{ width: collapsed ? 64 : 240 }}
    >
      {/* logo */}
      <div className="h-14 flex items-center gap-2.5 px-4 border-b border-[var(--border)] shrink-0">
        <div className="relative w-7 h-7 rounded-lg overflow-hidden flex items-center justify-center bg-accent-grad">
          <Sparkles className="w-4 h-4 text-white relative z-10" strokeWidth={2.2} />
          <div className="absolute inset-0 bg-white/15" />
        </div>
        {!collapsed && (
          <div className="flex flex-col leading-none">
            <span className="text-[15px] font-bold grad-text">Agent</span>
            <span className="text-[10px] text-fg2 tracking-[0.18em] uppercase">console</span>
          </div>
        )}
      </div>

      <nav className="flex-1 px-2 py-3 space-y-0.5 stagger">
        {items.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => cn('nav-item', isActive && 'active')}
          >
            <Icon className="w-[18px] h-[18px] shrink-0" strokeWidth={1.6} />
            {!collapsed && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      <div className="px-3 py-3 border-t border-[var(--border)] flex items-center justify-between shrink-0">
        {!collapsed ? (
          <div className="flex items-center gap-2 text-[11px] text-fg2">
            <span
              className={cn(
                'dot',
                online ? 'bg-[var(--success)] animate-pulse-soft' : 'bg-[var(--danger)]',
              )}
            />
            <span>{online ? 'Backend online' : 'Backend offline'}</span>
          </div>
        ) : (
          <span
            className={cn(
              'dot',
              online ? 'bg-[var(--success)] animate-pulse-soft' : 'bg-[var(--danger)]',
            )}
          />
        )}
        <button
          onClick={toggle}
          className="p-1.5 rounded-md text-fg2 hover:text-fg0 hover:bg-white/5 transition-colors"
          aria-label="toggle sidebar"
        >
          {collapsed ? <PanelLeftOpen className="w-4 h-4" /> : <PanelLeftClose className="w-4 h-4" />}
        </button>
      </div>
    </aside>
  );
}
