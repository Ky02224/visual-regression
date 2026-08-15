import React from 'react';

interface SidebarContextValue {
  collapsed: boolean;
  toggle: () => void;
}

const SidebarContext = React.createContext<SidebarContextValue>({ collapsed: false, toggle: () => {} });

export function SidebarProvider({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = React.useState(() => {
    // Below md, `collapsed` means "drawer closed" rather than "icon-only" —
    // a saved desktop preference of "expanded" would otherwise open the
    // drawer (plus its backdrop) over the very first mobile page load.
    if (typeof window !== 'undefined' && window.innerWidth < 768) return true;
    try { return localStorage.getItem('sidebar-collapsed') === 'true'; } catch { return false; }
  });

  const toggle = React.useCallback(() => {
    setCollapsed(prev => {
      const next = !prev;
      try { localStorage.setItem('sidebar-collapsed', String(next)); } catch {}
      return next;
    });
  }, []);

  return <SidebarContext.Provider value={{ collapsed, toggle }}>{children}</SidebarContext.Provider>;
}

export function useSidebar() {
  return React.useContext(SidebarContext);
}
