import React, { useEffect, useState } from 'react';
import { Menu, Sun, Moon } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { cn } from '../lib/utils';
import { useTheme } from './ThemeProvider';
import { useSidebar } from '../context/SidebarContext';

const PAGE_TITLES: Record<string, { title: string; sub: string }> = {
  '/': { title: 'Dashboard', sub: 'Visual change status across all runs' },
  '/actions': { title: 'Actions', sub: 'Run comparisons and suite tests' },
  '/baselines': { title: 'Baselines', sub: 'Manage snapshot baselines' },
  '/summaries': { title: 'Summaries', sub: 'Aggregated run summaries' },
  '/integrations': { title: 'Integrations', sub: 'External service configuration' },
  '/users': { title: 'User Management', sub: 'Roles and access control' },
};

export function TopBar() {
  const { collapsed, toggle } = useSidebar();
  const [backendStatus, setBackendStatus] = useState<'connected' | 'error'>('connected');
  const { theme, setTheme } = useTheme();
  const location = useLocation();

  useEffect(() => {
    const check = () => fetch('/api/dashboard').then(r => setBackendStatus(r.ok ? 'connected' : 'error')).catch(() => setBackendStatus('error'));
    check();
    const t = setInterval(check, 30000);
    return () => clearInterval(t);
  }, []);

  let page = PAGE_TITLES[location.pathname];
  if (!page) {
    if (location.pathname.startsWith('/report/')) page = { title: 'Report review', sub: 'Visual comparison workspace' };
    else if (location.pathname.startsWith('/suite/')) page = { title: decodeURIComponent(location.pathname.split('/suite/')[1] || 'Suite'), sub: 'Suite execution results' };
    else page = { title: 'The Lens', sub: '' };
  }

  const isReport = location.pathname.startsWith('/report/');

  return (
    <header className={cn('h-16 fixed top-0 right-0 z-30 transition-all duration-200 bg-[var(--surface)] border-b border-[var(--outline)] flex items-center justify-between px-4', collapsed ? 'left-16' : 'left-64', isReport && 'border-b')}>
      <div className="flex items-center gap-3 min-w-0">
        <button onClick={toggle} className="w-9 h-9 rounded-md flex items-center justify-center text-[var(--on-surface-variant)] hover:bg-stone-100 dark:hover:bg-zinc-800" title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
          <Menu className="w-5 h-5" />
        </button>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-[var(--on-surface)] truncate">{page.title}</p>
          {page.sub && <p className="text-xs text-[var(--on-surface-variant)] truncate">{page.sub}</p>}
        </div>
      </div>
      <div className="flex items-center gap-3">
        <span className={cn('hidden sm:inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border', backendStatus === 'connected' ? 'border-stone-200 dark:border-zinc-700 text-[var(--on-surface-variant)]' : 'border-red-200 text-red-600 dark:border-red-900 dark:text-red-400')}>
          <span className={cn('w-1.5 h-1.5 rounded-full', backendStatus === 'connected' ? 'bg-green-500' : 'bg-red-500')} />
          {backendStatus === 'connected' ? 'Engine connected' : 'Engine offline'}
        </span>
        <button onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')} className="w-9 h-9 rounded-md flex items-center justify-center text-[var(--on-surface-variant)] hover:bg-stone-100 dark:hover:bg-zinc-800">
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </div>
    </header>
  );
}
