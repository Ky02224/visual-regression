/** Percy-style review workflow states */
export type ReviewStatus = 'no_changes' | 'unreviewed' | 'approved' | 'rejected';

export const REVIEW_STATUS_LABELS: Record<ReviewStatus, string> = {
  no_changes: 'No changes',
  unreviewed: 'Unreviewed changes',
  approved: 'Approved',
  rejected: 'Rejected',
};

export function normalizeReviewStatus(raw: unknown): ReviewStatus {
  const value = String(raw || '').toLowerCase();
  if (value === 'no_changes' || value === 'approved' || value === 'rejected' || value === 'unreviewed') {
    return value;
  }
  if (value === 'passed') return 'no_changes';
  if (value === 'attention' || value === 'pending') return 'unreviewed';
  if (value === 'failed') return 'unreviewed';
  return 'unreviewed';
}

export function reviewStatusBadgeClass(status: ReviewStatus): string {
  switch (status) {
    case 'no_changes':
    case 'approved':
      return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/40 dark:text-green-400 dark:border-green-900';
    case 'rejected':
      return 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-400 dark:border-red-900';
    case 'unreviewed':
      return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900';
    default:
      return 'bg-stone-100 text-stone-600 border-stone-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700';
  }
}

/** Mismatch % color only — independent of review status (Percy-style). */
export function mismatchPctClass(mismatch: number): string {
  if (mismatch >= 5) return 'text-red-600 dark:text-red-400';
  if (mismatch >= 1) return 'text-orange-500 dark:text-orange-400';
  return 'text-green-600 dark:text-green-400';
}

export function reviewBorderClass(status: ReviewStatus): string {
  switch (status) {
    case 'rejected':
      return 'border-l-red-400';
    case 'unreviewed':
      return 'border-l-amber-400';
    case 'approved':
    case 'no_changes':
      return 'border-l-green-400';
    default:
      return 'border-l-stone-300';
  }
}
