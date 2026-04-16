import React, { useState } from 'react';
import { Shield, User, UserCheck, Lock, X, ChevronRight } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { useRole, Role } from '../context/RoleContext';
import { cn } from '../lib/utils';

export function RoleSwitcher() {
  const { role, setRole } = useRole();
  const [showPinModal, setShowPinModal] = useState(false);
  const [pendingRole, setPendingRole] = useState<Role | null>(null);
  const [pin, setPin] = useState('');
  const [error, setError] = useState(false);

  const handleRoleSelect = async (newRole: Role) => {
    if (newRole === 'viewer') {
      await setRole('viewer');
      return;
    }
    
    if (role !== newRole) {
      setPendingRole(newRole);
      setShowPinModal(true);
      return;
    }
  };

  const handlePinSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!pendingRole) return;

    const success = await setRole(pendingRole, pin);
    if (success) {
      setShowPinModal(false);
      setPendingRole(null);
      setPin('');
      setError(false);
    } else {
      setError(true);
      setPin('');
    }
  };

  return (
    <div className="space-y-4">
      <p className="px-4 text-[10px] font-bold uppercase tracking-[0.2em] text-white/30 font-mono">Laboratory Identity</p>
      
      <div className="px-2 space-y-1">
        <RoleButton 
          active={role === 'admin'} 
          label="Admin" 
          icon={<Shield className="w-4 h-4" />} 
          onClick={() => handleRoleSelect('admin')}
          isLocked={role !== 'admin'}
        />
        <RoleButton 
          active={role === 'developer'} 
          label="Developer" 
          icon={<UserCheck className="w-4 h-4" />} 
          onClick={() => handleRoleSelect('developer')}
          isLocked={role !== 'developer' && role !== 'admin'}
        />
        <RoleButton 
          active={role === 'viewer'} 
          label="Viewer" 
          icon={<User className="w-4 h-4" />} 
          onClick={() => handleRoleSelect('viewer')}
        />
      </div>

      <AnimatePresence>
        {showPinModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm">
            <motion.div 
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              className="bg-white dark:bg-slate-900 rounded-3xl p-8 w-full max-w-sm shadow-2xl border border-slate-200 dark:border-slate-800"
            >
              <div className="flex justify-between items-start mb-6">
                <div className="p-3 rounded-2xl bg-primary/10 text-primary">
                  <Lock className="w-6 h-6" />
                </div>
                <button onClick={() => setShowPinModal(false)} className="p-2 hover:bg-slate-100 dark:hover:bg-slate-800 rounded-full transition-colors text-slate-400">
                  <X className="w-5 h-5" />
                </button>
              </div>

              <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-2">Elevate Privileges</h3>
              <p className="text-sm text-slate-500 mb-6">
                Enter the access key to assume the <span className={cn("font-bold capitalize", pendingRole === 'admin' ? "text-primary" : "text-accent")}>{pendingRole}</span> role.
              </p>

              <form onSubmit={handlePinSubmit} className="space-y-4">
                <div className="relative">
                  <input
                    type="password"
                    autoFocus
                    value={pin}
                    onChange={(e) => setPin(e.target.value)}
                    placeholder={pendingRole === 'admin' ? "Admin PIN (1234)" : "Dev PIN (0000)"}
                    className={cn(
                      "w-full bg-slate-50 dark:bg-slate-950 border rounded-xl py-4 px-4 text-center text-2xl tracking-[0.5em] font-mono focus:ring-4 focus:ring-primary/10 outline-none transition-all dark:text-white",
                      error ? "border-red-500 animate-shake" : "border-slate-200 dark:border-slate-800"
                    )}
                  />
                  {error && <p className="text-center text-xs text-red-500 font-bold mt-2 uppercase tracking-widest">Access Denied</p>}
                </div>

                <button 
                  type="submit"
                  className="w-full py-4 bg-primary text-white rounded-xl font-bold shadow-lg shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-2"
                >
                  Verify Key
                  <ChevronRight className="w-4 h-4" />
                </button>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}

function RoleButton({ active, label, icon, onClick, isLocked }: { active: boolean, label: string, icon: React.ReactNode, onClick: () => void, isLocked?: boolean }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "w-full flex items-center gap-3 px-4 py-2.5 rounded-xl transition-all duration-300 group relative overflow-hidden",
        active 
          ? "bg-accent/10 text-accent" 
          : "text-white/40 hover:text-white hover:bg-white/5"
      )}
    >
      <div className={cn(
        "transition-transform duration-300 group-hover:scale-110",
        active ? "text-accent" : "text-white/30 group-hover:text-white/60"
      )}>
        {icon}
      </div>
      <span className="text-xs font-bold tracking-tight">{label}</span>
      {active && (
        <div className="ml-auto w-1 h-1 rounded-full bg-accent" />
      )}
      {!active && isLocked && (
        <Lock className="ml-auto w-3 h-3 text-white/20" />
      )}
    </button>
  );
}
