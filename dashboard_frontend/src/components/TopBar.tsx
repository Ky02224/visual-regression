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
  '/summaries': { title: 'Builds', sub: 'All test runs — suite executions and CI builds' },
  '/integrations': { title: 'Integrations', sub: 'External service configuration' },
  '/users': { title: 'User Management', sub: 'Roles and access control' },
};

import { useSSE } from '../hooks/useSSE';

export function TopBar() {
  const { collapsed, toggle } = useSidebar();
  const { theme, setTheme } = useTheme();
  const location = useLocation();

  const [activeTask, setActiveTask] = useState<{
    status: string;
    completed: number;
    total: number;
    label: string;
    url?: string;
  } | null>(null);

  const [showTasksDropdown, setShowTasksDropdown] = useState(false);

  const { isConnected } = useSSE('/api/events/stream', {
    onEvent: (event) => {
      if (event.type === 'task_started') {
        const cmd = event.data.cmd || '';
        let label = 'Running';
        if (cmd.includes('create-multiple-baselines') || cmd.includes('crawl')) {
          label = 'Capturing';
        } else if (cmd.includes('compare-matrix')) {
          label = 'Matrix Comp';
        } else if (cmd.includes('compare')) {
          label = 'Comparing';
        } else if (cmd.includes('run-suite')) {
          label = 'Suite';
        }
        setActiveTask({
          status: 'running',
          completed: 0,
          total: 0,
          label
        });
      } else if (event.type === 'capture_progress') {
        setActiveTask(prev => ({
          status: 'running',
          completed: event.data.completed || 0,
          total: event.data.total || 0,
          url: event.data.url,
          label: prev?.label || 'Capturing'
        }));
      } else if (
        event.type === 'task_completed' || 
        event.type === 'task_failed' ||
        (event.type === 'task_progress' && (event.data.status === 'completed' || event.data.status === 'failed'))
      ) {
        setActiveTask(null);
        setShowTasksDropdown(false);
      }
    }
  });

  const backendStatus = isConnected ? 'connected' : 'error';

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
        {activeTask && (
          <div className="relative">
            <button
              onClick={() => setShowTasksDropdown(!showTasksDropdown)}
              className="flex items-center gap-2 bg-indigo-50 dark:bg-indigo-950/30 border border-indigo-100 dark:border-indigo-900/50 rounded-md px-2.5 py-1 text-xs text-indigo-700 dark:text-indigo-300 hover:bg-indigo-100/50 dark:hover:bg-indigo-950/50 transition-all cursor-pointer select-none"
            >
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
              <span className="font-semibold">
                {activeTask.label}: running...
              </span>
            </button>

            {showTasksDropdown && (
              <div className="absolute right-0 mt-2 w-64 bg-white dark:bg-zinc-900 rounded-xl border border-stone-200 dark:border-zinc-800 shadow-xl p-4 z-50 animate-in fade-in slide-in-from-top-2 duration-200">
                <div className="flex items-center justify-between border-b border-stone-100 dark:border-zinc-850 pb-2 mb-3">
                  <span className="text-xs font-bold text-stone-700 dark:text-stone-300">Active Task</span>
                  <span className="px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400">
                    Running
                  </span>
                </div>
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs font-medium">
                    <span className="text-stone-600 dark:text-stone-400">{activeTask.label} Job</span>
                  </div>
                  
                  <div className="w-full bg-stone-100 dark:bg-zinc-800 rounded-full h-1.5 overflow-hidden relative">
                    <div 
                      className={cn(
                        "bg-indigo-500 h-full transition-all duration-500 ease-out rounded-full",
                        activeTask.total > 0 ? "relative" : "absolute w-[30%] animate-indeterminate"
                      )} 
                      style={
                        activeTask.total > 0 
                          ? { width: `${(activeTask.completed / activeTask.total) * 100}%` }
                          : undefined
                      } 
                    />
                  </div>

                  {activeTask.url && (
                    <div className="text-[10px] text-stone-400 dark:text-stone-500 break-all font-mono leading-tight bg-stone-50 dark:bg-zinc-950 p-2 rounded-lg border border-stone-100/50 dark:border-zinc-850">
                      <span className="text-stone-500 dark:text-stone-400 font-bold block mb-0.5">URL:</span>
                      {activeTask.url}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
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
