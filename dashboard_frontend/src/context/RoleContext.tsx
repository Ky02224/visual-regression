import React, { createContext, useContext, useState, useEffect } from 'react';

export type Role = 'admin' | 'developer' | 'viewer';

interface RoleContextType {
  role: Role;
  setRole: (role: Role, pin?: string) => Promise<boolean>;
  can: (action: 'approve' | 'capture' | 'manage_baselines') => boolean;
  accessKey: string | null;
}

const RoleContext = createContext<RoleContextType | undefined>(undefined);

// Use environment variables for security. Fallbacks are provided for local development.
const ADMIN_PIN = import.meta.env.VITE_ADMIN_PIN || '1234';
const DEVELOPER_PIN = import.meta.env.VITE_DEVELOPER_PIN || '0000';
const ADMIN_KEY = import.meta.env.VITE_ADMIN_KEY || 'lead-scientist-secure-key-2024';
const DEVELOPER_KEY = import.meta.env.VITE_DEVELOPER_KEY || 'technician-working-key-2024';

export const RoleProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [role, setRoleState] = useState<Role>(() => {
    return (localStorage.getItem('lab-identity-role') as Role) || 'viewer';
  });
  const [accessKey, setAccessKey] = useState<string | null>(() => {
    return localStorage.getItem('lab-access-key');
  });

  const setRole = async (newRole: Role, pin?: string): Promise<boolean> => {
    if (newRole === 'admin') {
      if (pin === ADMIN_PIN) {
        setRoleState('admin');
        setAccessKey(ADMIN_KEY);
        localStorage.setItem('lab-identity-role', 'admin');
        localStorage.setItem('lab-access-key', ADMIN_KEY);
        return true;
      }
      return false;
    }

    if (newRole === 'developer') {
      if (pin === DEVELOPER_PIN) {
        setRoleState('developer');
        setAccessKey(DEVELOPER_KEY);
        localStorage.setItem('lab-identity-role', 'developer');
        localStorage.setItem('lab-access-key', DEVELOPER_KEY);
        return true;
      }
      return false;
    }

    setRoleState('viewer');
    setAccessKey(null);
    localStorage.setItem('lab-identity-role', 'viewer');
    localStorage.removeItem('lab-access-key');
    return true;
  };

  const can = (action: 'approve' | 'capture' | 'manage_baselines'): boolean => {
    if (role === 'admin') return true;
    if (role === 'developer') {
      return action === 'capture';
    }
    return false; // viewer can do nothing
  };

  return (
    <RoleContext.Provider value={{ role, setRole, can, accessKey }}>
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
