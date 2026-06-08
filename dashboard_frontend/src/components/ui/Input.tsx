import React from 'react';
import { cn } from '../../lib/utils';

export function Input({ label, className, id, ...props }: React.InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  const inputId = id || label?.toLowerCase().replace(/\s+/g, '-');
  return (
    <div className="space-y-1.5">
      {label && <label htmlFor={inputId} className="block text-sm font-medium text-[var(--on-surface)]">{label}</label>}
      <input id={inputId} className={cn('w-full px-3 py-2 text-sm rounded-md border border-[var(--outline)] bg-[var(--surface)] outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500', className)} {...props} />
    </div>
  );
}
