import React from 'react';
import { Layers, Lock, Mail, ArrowRight, Github, Chrome } from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '../lib/utils';

export function Login() {
  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-6 font-sans antialiased selection:bg-primary/20">
      {/* Ambient Background Effects */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[-10%] left-[-10%] w-[40%] h-[40%] bg-primary/5 rounded-full blur-[120px]" />
        <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-blue-400/5 rounded-full blur-[120px]" />
      </div>

      <motion.div 
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-md"
      >
        <div className="text-center mb-10">
          <div className="w-16 h-16 bg-white rounded-2xl shadow-xl flex items-center justify-center mx-auto mb-6 ghost-border">
            <div className="w-10 h-10 rounded-lg signature-gradient flex items-center justify-center text-white">
              <Layers className="w-6 h-6" />
            </div>
          </div>
          <h1 className="text-3xl font-bold tracking-tight text-blue-900 mb-2">The Analytical Lens</h1>
          <p className="text-on-surface-variant font-medium">Precision Visual Regression Laboratory</p>
        </div>

        <div className="bg-white rounded-3xl p-10 shadow-2xl shadow-primary/5 ghost-border relative overflow-hidden">
          <div className="space-y-6">
            <div className="space-y-2">
              <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant px-1">Laboratory Email</label>
              <div className="relative">
                <Mail className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" />
                <input 
                  type="email" 
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="technician@analytical-lens.io"
                  className="w-full bg-slate-50 border border-slate-100 rounded-xl py-3.5 pl-12 pr-4 text-sm focus:bg-white focus:ring-2 focus:ring-primary/10 outline-none transition-all"
                />
              </div>
            </div>

            <div className="space-y-2">
              <div className="flex justify-between px-1">
                <label className="text-xs font-bold uppercase tracking-widest text-on-surface-variant">Access Key</label>
                <button className="text-[10px] font-bold text-primary hover:underline">Forgot Key?</button>
              </div>
              <div className="relative">
                <Lock className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-on-surface-variant" />
                <input 
                  type="password" 
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••••••"
                  className="w-full bg-slate-50 border border-slate-100 rounded-xl py-3.5 pl-12 pr-4 text-sm focus:bg-white focus:ring-2 focus:ring-primary/10 outline-none transition-all"
                />
              </div>
            </div>

            <button className="w-full py-4 signature-gradient text-white rounded-xl font-bold shadow-xl shadow-primary/20 hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-2 group">
              Initialize Session
              <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
            </button>

            <div className="relative py-4">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-slate-100"></div>
              </div>
              <div className="relative flex justify-center text-[10px] uppercase tracking-widest font-bold text-on-surface-variant">
                <span className="bg-white px-4">External Authentication</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <button className="flex items-center justify-center gap-2 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-bold text-on-surface hover:bg-slate-100 transition-all">
                <Github className="w-4 h-4" />
                GitHub
              </button>
              <button className="flex items-center justify-center gap-2 py-3 bg-slate-50 border border-slate-100 rounded-xl text-sm font-bold text-on-surface hover:bg-slate-100 transition-all">
                <Chrome className="w-4 h-4" />
                Google
              </button>
            </div>
          </div>
        </div>

        <p className="text-center mt-8 text-sm text-on-surface-variant">
          New technician? <button className="text-primary font-bold hover:underline">Request Laboratory Access</button>
        </p>
      </motion.div>
    </div>
  );
}
