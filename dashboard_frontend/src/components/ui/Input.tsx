import React from 'react';
import { Eye, EyeOff } from 'lucide-react';
import { cn } from '../../lib/utils';

export function Input({ label, className, id, type, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');
  const isPassword = type === 'password';
  const [showPassword, setShowPassword] = React.useState(false);

  const resolvedType = isPassword ? (showPassword ? 'text' : 'password') : type;

  return (
    <div className="space-y-1.5 w-full">
      {label && <label htmlFor={inputId} className="block text-sm font-medium text-[var(--on-surface)]">{label}</label>}
      <div className="relative w-full flex items-center">
        <input
          id={inputId}
          type={resolvedType}
          className={cn(
            'w-full px-3 py-2 text-sm rounded-md border border-[var(--outline)] bg-[var(--surface)] outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 dark:text-slate-100',
            isPassword && 'pr-10',
            className
          )}
          {...props}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setShowPassword(prev => !prev)}
            className="absolute right-3 p-1 rounded hover:bg-stone-100 dark:hover:bg-zinc-800 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors flex items-center justify-center"
            title={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
          </button>
        )}
      </div>
    </div>
  );
}
