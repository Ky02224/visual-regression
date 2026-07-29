import React, { createContext, useContext, useState, useEffect } from 'react';
import { clearApiCache } from '../hooks/useApiData';

export type Role = 'admin' | 'developer' | 'viewer';

interface RoleContextType {
  role: Role;
  userEmail: string | null;
  userName: string | null;
  authenticated: boolean;
  loading: boolean;
  login: (email: string, password: string) => Promise<{ ok: boolean; error?: string }>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  can: (action: 'approve' | 'capture' | 'manage_baselines') => boolean;
}

const RoleContext = createContext<RoleContextType | undefined>(undefined);

type MeResponse = {
  ok: boolean;
  authenticated: boolean;
  user: { email: string; role: Role; name?: string } | null;
};

export const RoleProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [role, setRoleState] = useState<Role>('viewer');
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [userName, setUserName] = useState<string | null>(null);
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);

  const refreshSession = async () => {
    try {
      const res = await fetch('/api/auth/me', { credentials: 'include' });
      const data = (await res.json()) as MeResponse;
      if (data.ok && data.authenticated && data.user) {
        setAuthenticated(true);
        setRoleState(data.user.role);
        setUserEmail(data.user.email);
        setUserName(data.user.name || null);
        setLoading(false);
        return;
      }
    } catch {
      // ignore
    }
    setAuthenticated(false);
    setRoleState('viewer');
    setUserEmail(null);
    setUserName(null);
    setLoading(false);
  };

  useEffect(() => {
    refreshSession();
  }, []);

  const login = async (email: string, password: string) => {
    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        return { ok: false, error: data.error || 'Login failed' };
      }
      await refreshSession();
      return { ok: true };
    } catch {
      return { ok: false, error: 'Network failure' };
    }
  };

  const logout = async () => {
    try {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
    } finally {
      clearApiCache();
      await refreshSession();
    }
  };

  const can =(action: 'approve' | 'capture' | 'manage_baselines'): boolean => {
    if (role === 'admin') return true;
    if (role === 'developer') {
      return action === 'capture';
    }
    return false; // viewer can do nothing
  };

  return (
    <RoleContext.Provider
      value={{
        role,
        userEmail,
        userName,
        authenticated,
        loading,
        login,
        logout,
        refreshSession,
        can,
      }}
    >
      {children}
    </RoleContext.Provider>
  );
};

export const useRole = () => {
  const context = useContext(RoleContext);
  if (context === undefined) {
    throw new Error('useRole must be used within a RoleProvider');
  }
  return context;
};
