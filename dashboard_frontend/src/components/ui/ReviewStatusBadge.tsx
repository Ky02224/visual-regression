import React from 'react';
import { cn } from '../../lib/utils';
import { reviewStatusBadgeClass, REVIEW_STATUS_LABELS, type ReviewStatus } from '../../lib/reviewStatus';

export function ReviewStatusBadge({ status, className }: { status: ReviewStatus; className?: string }) {
  return (
    <span className={cn('inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border', reviewStatusBadgeClass(status), className)}>
      {REVIEW_STATUS_LABELS[status]}
    </span>
  );
}
