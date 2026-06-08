import React from 'react';
import { cn, statusBadgeClass, type RunStatus } from '../../lib/utils';

export function Badge({ status = 'unknown', children, className }: { status?: RunStatus; children: React.ReactNode; className?: string }) {
  return <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded border', statusBadgeClass(status), className)}>{children}</span>;
}
