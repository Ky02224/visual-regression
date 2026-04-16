import React from 'react';
import { NavLink } from 'react-router-dom';
import { 
  LayoutDashboard, 
  PlayCircle, 
  Ruler, 
  Layers, 
  FileText,
  Cpu
} from 'lucide-react';
import { cn } from '../lib/utils';

import { RoleSwitcher } from './RoleSwitcher';
import { useRole } from '../context/RoleContext';
import { Lock } from 'lucide-react';

const restrictedItems = ['Actions', 'Baselines', 'Integrations'];

const navItems = [
  { icon: LayoutDashboard, label: 'Dashboard', to: '/' },
  { icon: PlayCircle, label: 'Actions', to: '/actions' },
  { icon: Ruler, label: 'Baselines', to: '/baselines' },
  { icon: FileText, label: 'Summaries', to: '/summaries' },
  { icon: Cpu, label: 'Integrations', to: '/integrations' },
];

export function Sidebar() {
  const { role } = useRole();
  return (
    <aside className="h-screen w-64 fixed left-0 top-0 flex flex-col bg-sidebar-bg/95 backdrop-blur-xl border-r border-white/10 dark:border-white/5 z-40 font-sans antialiased text-sm tracking-tight transition-colors duration-300 shadow-2xl">
      <div className="p-8">
        <div className="flex items-center gap-4">
          <div className="w-10 h-10 rounded-xl bg-accent flex items-center justify-center text-white shadow-lg shadow-accent/20">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold tracking-tighter text-white leading-tight font-mono">THE<br/>LENS</h1>
          </div>
        </div>
      </div>

      <div className="px-4 mb-4">
        <div className="h-px bg-white/10 w-full" />
      </div>

      <nav className="flex-1 px-4 space-y-1.5 overflow-y-auto custom-scrollbar">
        <p className="px-4 py-2 text-[10px] font-bold uppercase tracking-[0.2em] text-white/30 font-mono">Navigation</p>
        {navItems.map((item) => {
          const isRestricted = role === 'viewer' && restrictedItems.includes(item.label);

          if (isRestricted) {
            return (
              <div
                key={item.to}
                className="flex items-center gap-3 px-4 py-3 rounded-xl opacity-40 cursor-not-allowed text-white/30"
                title="Admin or Developer privileges required"
              >
                <item.icon className="w-5 h-5" />
                <span className="font-medium">{item.label}</span>
                <Lock className="ml-auto w-3 h-3 opcity-50" />
              </div>
            );
          }

          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => cn(
                "flex items-center gap-3 px-4 py-3 rounded-xl transition-all duration-300 group",
                isActive 
                  ? "bg-white/10 text-white shadow-sm" 
                  : "text-white/50 hover:text-white hover:bg-white/5"
              )}
            >
              <item.icon className={cn(
                "w-5 h-5 transition-transform duration-300 group-hover:scale-110",
                "group-[.active]:text-accent"
              )} />
              <span className="font-medium">{item.label}</span>
              {item.label === 'Actions' && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-accent animate-pulse shadow-[0_0_8px_rgba(37,99,235,0.6)]" />
              )}
            </NavLink>
          );
        })}
      </nav>

      <div className="p-4 mt-auto border-t border-white/5">
        <RoleSwitcher />
      </div>
    </aside>
  );
}
