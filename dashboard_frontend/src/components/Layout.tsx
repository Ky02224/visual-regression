import React, { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { SidebarProvider, useSidebar } from '../context/SidebarContext';
import { cn } from '../lib/utils';
import { useSSE } from '../hooks/useSSE';

interface Toast {
  id: string;
  type: 'success' | 'error' | 'info';
  message: string;
}

function LayoutInner() {
  const { collapsed } = useSidebar();
  const location = useLocation();
  const isReport = location.pathname.startsWith('/report/');
  const [toasts, setToasts] = useState<Toast[]>([]);

  useSSE('/api/events/stream', {
    onEvent: (event) => {
      let toastType: 'success' | 'error' | 'info' = 'info';
      let message = '';

      if (event.type === 'task_completed') {
        toastType = 'success';
        message = `Task completed successfully: ${event.data.cmd || 'Regression run'}`;
      } else if (event.type === 'task_failed') {
        toastType = 'error';
        message = `Task failed: ${event.data.stderr || event.data.error || 'Error executing task'}`;
      } else if (event.type === 'compare_completed') {
        toastType = event.data.passed ? 'success' : 'error';
        message = `Comparison completed: ${event.data.name} (${event.data.passed ? 'PASSED' : 'FAILED'})`;
      } else if (event.type === 'compare_failed') {
        toastType = 'error';
        message = `Comparison failed for ${event.data.name}: ${event.data.error}`;
      } else {
        return;
      }

      const id = Math.random().toString(36).substring(2, 9);
      setToasts(prev => [...prev, { id, type: toastType, message }]);
      
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, 5000);
    }
  });

  return (
    <div className="min-h-screen bg-[var(--bg-main)] transition-colors duration-200">
      <Sidebar />
      <TopBar />
      <main className={cn('ml-0', collapsed ? 'md:ml-16' : 'md:ml-64', 'pt-16 relative z-10 transition-all duration-200', isReport ? 'h-screen overflow-hidden' : 'min-h-screen')}>
        <Outlet />
      </main>

      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map(t => (
          <div
            key={t.id}
            className={cn(
              "p-3 rounded-lg shadow-lg text-white text-xs font-medium flex items-center justify-between gap-3 transition-all duration-300 animate-in fade-in slide-in-from-bottom-2",
              t.type === 'success' && 'bg-green-600 dark:bg-green-700',
              t.type === 'error' && 'bg-red-600 dark:bg-red-700',
              t.type === 'info' && 'bg-blue-600 dark:bg-blue-700'
            )}
          >
            <span>{t.message}</span>
            <button
              onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}
              className="text-white hover:text-stone-200 font-bold ml-2"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Layout() {
  return (
    <SidebarProvider>
      <LayoutInner />
    </SidebarProvider>
  );
}
