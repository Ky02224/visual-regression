import React from 'react';
import { cn, formatChangeType, changeTypeBadgeClass } from '../../lib/utils';

export function ChangeTypeBadge({ label, className }: { label?: string | null; className?: string }) {
  const text = formatChangeType(label ?? undefined);
  if (!text) return null;
  const key = (label ?? '').toLowerCase().replace(/_/g, '-');
  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border', changeTypeBadgeClass(key), className)}>
      {text}
    </span>
  );
}
