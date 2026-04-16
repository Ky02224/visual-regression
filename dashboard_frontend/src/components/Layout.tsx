import React from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

export function Layout() {
  return (
    <div className="min-h-screen bg-[var(--bg-main)] transition-colors duration-300">
      <Sidebar />
      <TopBar />
      <main className="ml-64 pt-16 min-h-screen relative z-10">
        <Outlet />
      </main>
      
      {/* Laboratory Ambient Elements */}
      <div className="fixed inset-0 pointer-events-none z-0 overflow-hidden">
        <div className="absolute top-0 right-0 w-full h-full corporate-grid opacity-20" />
        <div className="absolute -top-40 -right-40 w-[600px] h-[600px] bg-accent/20 rounded-full blur-[120px]" />
        <div className="absolute bottom-1/4 -left-40 w-96 h-96 bg-[var(--color-cyber-magenta)]/5 rounded-full blur-[100px]" />
        <div className="absolute top-1/4 left-1/3 w-80 h-80 bg-[var(--color-cyber-green)]/5 rounded-full blur-[120px]" />
      </div>
    </div>
  );
}
