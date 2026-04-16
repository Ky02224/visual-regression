import React, { useState, useEffect } from 'react';
import { Cpu, ChevronDown, Activity, Database, Sun, Moon, Brain } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { useTheme } from './ThemeProvider';

// Data will be fetched from /api/dashboard

export function TopBar() {
  const [isOpen, setIsOpen] = React.useState(false);
  const [models, setModels] = React.useState<any[]>([]);
  const [backendStatus, setBackendStatus] = useState<'connected' | 'error'>('connected');
  const { theme, setTheme } = useTheme();

  // Backend Heartbeat Sentinel
  useEffect(() => {
    const checkConn = () => {
      fetch('/api/dashboard', { method: 'GET' })
        .then(res => {
          if (res.ok) setBackendStatus('connected');
          else setBackendStatus('error');
        })
        .catch(() => setBackendStatus('error'));
    };
    
    const timer = setInterval(checkConn, 5000);
    checkConn();
    return () => clearInterval(timer);
  }, []);

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        if (data.models) setModels(data.models);
      })
      .catch(() => {});
  }, []);

  return (
    <header className="h-16 fixed top-0 right-0 left-64 z-30 bg-white/60 dark:bg-slate-950/80 backdrop-blur-xl border-b border-white/20 dark:border-slate-800 flex items-center justify-between px-10 font-sans text-sm font-medium transition-colors duration-300 shadow-sm">
      <div className="flex items-center gap-8">
      </div>

      <div className="flex items-center gap-6">
        <button
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
          className="w-10 h-10 rounded-full flex items-center justify-center bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
        >
          {theme === 'dark' ? <Moon className="w-4 h-4" /> : <Sun className="w-4 h-4" />}
        </button>

        {/* Local AI Status Indicator */}
        <div className="relative">
          <button 
            onClick={() => setIsOpen(!isOpen)}
            className={cn(
              "flex items-center gap-3 px-4 py-2 rounded-xl transition-all duration-300 border border-transparent",
              isOpen 
                ? "bg-indigo-600 text-white shadow-lg shadow-indigo-600/20" 
                : "bg-slate-50 dark:bg-slate-900 border-slate-100 dark:border-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800"
            )}
          >
            <div className="relative">
              <Brain className={cn("w-4 h-4", isOpen ? "text-white" : backendStatus === 'connected' ? "text-indigo-500" : "text-red-500")} />
              <span className={cn(
                "absolute -top-1 -right-1 w-2 h-2 rounded-full border-2 border-white dark:border-slate-950",
                backendStatus === 'connected' ? "bg-green-500 animate-pulse" : "bg-red-500 animate-bounce"
              )} />
            </div>
            <div className="flex flex-col items-start leading-none">
              <span className="text-[9px] font-black uppercase tracking-widest opacity-60">Neural Core</span>
              <span className="text-xs font-bold">
                {models[0] ? `${(models[0].accuracy * 100).toFixed(1)}% Acc` : "Ready"}
              </span>
            </div>
            <ChevronDown className={cn("w-3 h-3 transition-transform opacity-40", isOpen && "rotate-180")} />
          </button>

          <AnimatePresence>
            {isOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
                <motion.div
                  initial={{ opacity: 0, y: 10, scale: 0.95 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 10, scale: 0.95 }}
                  className="absolute right-0 mt-3 w-80 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl z-50 overflow-hidden"
                >
                  <div className="p-4 bg-slate-50 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
                    <h4 className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Active Neural Models</h4>
                    <Activity className="w-3 h-3 text-green-500" />
                  </div>
                    <div className="p-2">
                      {models.length > 0 ? models.map((model, idx) => (
                        <div key={idx} className="p-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors flex items-center justify-between group">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center text-indigo-500">
                              <Database className="w-4 h-4" />
                            </div>
                            <div>
                              <p className="text-xs font-bold text-slate-900 dark:text-slate-100">Local Siamese Engine</p>
                              <p className="text-[10px] text-slate-400 font-medium">ResNet50 • {(model.accuracy * 100).toFixed(1)}% Acc</p>
                            </div>
                          </div>
                          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded uppercase tracking-tighter bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400">
                            Active
                          </span>
                        </div>
                      )) : (
                        <p className="p-4 text-center text-[10px] text-slate-400 font-bold uppercase tracking-widest">No Active Models</p>
                      )}
                    </div>
                </motion.div>
              </>
            )}
          </AnimatePresence>
        </div>
      </div>
    </header>
  );
}
