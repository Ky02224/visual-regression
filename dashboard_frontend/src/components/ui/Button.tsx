import React from 'react';
import { cn } from '../../lib/utils';

type ButtonVariant = 'primary' | 'approve' | 'secondary' | 'ghost' | 'danger';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: 'sm' | 'md' | 'lg';
}

const variants: Record<ButtonVariant, string> = {
  primary: 'bg-indigo-600 hover:bg-indigo-700 text-white dark:bg-indigo-500 dark:hover:bg-indigo-600',
  approve: 'bg-[var(--approve)] hover:bg-[var(--approve-hover)] text-white',
  secondary: 'bg-[var(--surface)] border border-[var(--outline)] text-[var(--on-surface)] hover:bg-stone-50 dark:hover:bg-zinc-800',
  ghost: 'text-[var(--on-surface-variant)] hover:bg-stone-50 dark:hover:bg-zinc-800',
  danger: 'bg-red-600 hover:bg-red-700 text-white',
};

const sizes = { sm: 'px-2.5 py-1.5 text-xs', md: 'px-3.5 py-2 text-sm', lg: 'px-4 py-2.5 text-sm font-medium' };

export function Button({ variant = 'primary', size = 'md', className, children, ...props }: ButtonProps) {
  return (
    <button className={cn('inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed', variants[variant], sizes[size], className)} {...props}>
      {children}
    </button>
  );
}
