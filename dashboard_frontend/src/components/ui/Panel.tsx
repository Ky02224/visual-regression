import React from 'react';
import { cn } from '../../lib/utils';

export function Panel({ title, children, className }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn('panel', className)}>
      {title && <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-medium text-[var(--on-surface-variant)]">{title}</div>}
      <div className="p-3">{children}</div>
    </div>
  );
}
