import { MessageSquare } from 'lucide-react';
import { cn } from '../../lib/utils';

/**
 * A run's review-comment count.
 *
 * Comments are pinned inside one run's report, so before this badge existed a
 * question left on a run was seen only by someone who happened to open that
 * exact report. Renders nothing at zero — an empty badge on every row would
 * cost more attention than it returns.
 */
export function CommentCountBadge({ count, className }: { count?: number | null; className?: string }) {
  const total = Number(count) || 0;
  if (total < 1) return null;

  const label = `${total} review comment${total === 1 ? '' : 's'}`;
  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        'inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5',
        'text-[10px] font-bold text-indigo-700',
        'dark:border-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-300',
        className,
      )}
    >
      <MessageSquare className="w-3 h-3" aria-hidden="true" />
      {total}
    </span>
  );
}
