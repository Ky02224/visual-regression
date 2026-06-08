import React from 'react';
import { NavLink } from 'react-router-dom';
import { LayoutDashboard, PlayCircle, Ruler, Layers, FileText, Cpu, Users, Lock, LogOut, Shield, UserCheck, Eye } from 'lucide-react';
import { cn } from '../lib/utils';
import { useRole } from '../context/RoleContext';
import { useSidebar } from '../context/SidebarContext';

const restrictedItems = ['Actions', 'Baselines', 'Integrations'];
const navItems = [
  { icon: LayoutDashboard, label: 'Dashboard', to: '/' },
  { icon: PlayCircle, label: 'Actions', to: '/actions' },
  { icon: Ruler, label: 'Baselines', to: '/baselines' },
  { icon: FileText, label: 'Summaries', to: '/summaries' },
  { icon: Cpu, label: 'Integrations', to: '/integrations' },
];

const ROLE_COLOR: Record<string, string> = {
  admin: 'bg-rose-100 text-rose-700 dark:bg-rose-950/40 dark:text-rose-400',
  developer: 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950/40 dark:text-indigo-400',
  viewer: 'bg-stone-100 text-stone-600 dark:bg-zinc-800 dark:text-zinc-400',
};

export function Sidebar() {
  const { role, userEmail, userName, logout } = useRole();
  const { collapsed } = useSidebar();

  return (
    <aside className={cn('h-screen fixed left-0 top-0 flex flex-col bg-[var(--sidebar-bg)] border-r border-[var(--outline)] z-40 transition-all duration-200', collapsed ? 'w-16' : 'w-64')}>
      <div className={cn('flex items-center', collapsed ? 'p-3 justify-center' : 'p-5 gap-3')}>
        <div className="w-9 h-9 rounded-md bg-indigo-600 flex items-center justify-center text-white shrink-0"><Layers className="w-5 h-5" /></div>
        {!collapsed && (
          <div>
            <p className="text-sm font-semibold text-[var(--on-surface)] leading-tight">The Lens</p>
            <p className="text-[11px] text-[var(--on-surface-variant)]">Visual regression</p>
          </div>
        )}
      </div>
      <nav className="flex-1 px-2 space-y-0.5 overflow-y-auto">
        {!collapsed && <p className="px-3 py-2 text-xs text-[var(--on-surface-variant)]">Navigation</p>}
        {navItems.map((item) => {
          const isRestricted = role === 'viewer' && restrictedItems.includes(item.label);
          if (isRestricted) {
            return (
              <div key={item.to} className={cn('flex items-center rounded-md opacity-40 cursor-not-allowed text-[var(--on-surface-variant)]', collapsed ? 'justify-center p-3' : 'gap-3 px-3 py-2')} title={item.label}>
                <item.icon className="w-5 h-5 shrink-0" />
                {!collapsed && <><span className="text-sm">{item.label}</span><Lock className="ml-auto w-3 h-3" /></>}
              </div>
            );
          }
          return (
            <NavLink key={item.to} to={item.to} title={collapsed ? item.label : undefined} className={({ isActive }) => cn('flex items-center rounded-md text-sm transition-colors border-l-2', collapsed ? 'justify-center p-3' : 'gap-3 px-3 py-2', isActive ? 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300 border-indigo-600' : 'text-[var(--on-surface-variant)] hover:bg-stone-100 dark:hover:bg-zinc-800 border-transparent')}>
              <item.icon className="w-5 h-5 shrink-0" />
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          );
        })}
        {role === 'admin' && (
          <>
            {!collapsed && <p className="px-3 pt-4 pb-2 text-xs text-[var(--on-surface-variant)]">Administration</p>}
            <NavLink to="/users" title={collapsed ? 'Users' : undefined} className={({ isActive }) => cn('flex items-center rounded-md text-sm border-l-2', collapsed ? 'justify-center p-3' : 'gap-3 px-3 py-2', isActive ? 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300 border-indigo-600' : 'text-[var(--on-surface-variant)] hover:bg-stone-100 dark:hover:bg-zinc-800 border-transparent')}>
              <Users className="w-5 h-5 shrink-0" />
              {!collapsed && <span>Users</span>}
            </NavLink>
          </>
        )}
      </nav>
      <div className="mt-auto border-t border-[var(--outline)] p-3">
        <div className={cn('flex items-center', collapsed ? 'justify-center' : 'gap-3 px-1 mb-2')}>
          <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-950/50 text-indigo-700 dark:text-indigo-300 flex items-center justify-center text-sm font-semibold shrink-0">{(userName || userEmail || '?')[0].toUpperCase()}</div>
          {!collapsed && (
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium truncate">{userName || userEmail}</p>
              <span className={cn('inline-block text-[10px] font-medium px-1.5 py-0.5 rounded mt-0.5', ROLE_COLOR[role] ?? ROLE_COLOR.viewer)}>{role}</span>
            </div>
          )}
        </div>
        <button onClick={() => logout()} className={cn('flex items-center rounded-md text-xs text-[var(--on-surface-variant)] hover:bg-stone-100 dark:hover:bg-zinc-800 transition-colors', collapsed ? 'justify-center p-2 w-full' : 'gap-2 px-3 py-2 w-full')}>
          <LogOut className="w-4 h-4" />
          {!collapsed && 'Sign out'}
        </button>
      </div>
    </aside>
  );
}
