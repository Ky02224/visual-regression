import React from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';
import { SidebarProvider, useSidebar } from '../context/SidebarContext';
import { cn } from '../lib/utils';

function LayoutInner() {
  const { collapsed } = useSidebar();
  const location = useLocation();
  const isReport = location.pathname.startsWith('/report/');

  return (
    <div className="min-h-screen bg-[var(--bg-main)] transition-colors duration-200">
      <Sidebar />
      <TopBar />
      <main className={cn(collapsed ? 'ml-16' : 'ml-64', 'pt-16 relative z-10 transition-all duration-200', isReport ? 'h-screen overflow-hidden' : 'min-h-screen')}>
        <Outlet />
      </main>
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
