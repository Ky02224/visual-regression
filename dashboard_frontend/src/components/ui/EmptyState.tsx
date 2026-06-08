import React from 'react';
import { cn } from '../../lib/utils';

export function EmptyState({ icon, title, description, action, className }: { icon: React.ReactNode; title: string; description?: string; action?: React.ReactNode; className?: string }) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center px-6 py-10 gap-2', className)}>
      <div className="text-stone-400 dark:text-zinc-500 mb-1">{icon}</div>
      <p className="text-sm font-medium text-[var(--on-surface)]">{title}</p>
      {description && <p className="text-xs text-[var(--on-surface-variant)] max-w-xs">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
