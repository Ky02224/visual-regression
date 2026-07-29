import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export type RunStatus = 'passed' | 'failed' | 'attention' | 'pending' | 'approved' | 'no_changes' | 'unreviewed' | 'rejected' | 'unknown';

export function statusBadgeClass(status: RunStatus): string {
  switch (status) {
    case 'passed':
    case 'approved':
    case 'no_changes':
      return 'bg-green-50 text-green-700 border-green-200 dark:bg-green-950/40 dark:text-green-400 dark:border-green-900';
    case 'failed':
    case 'rejected':
      return 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-400 dark:border-red-900';
    case 'attention':
    case 'pending':
    case 'unreviewed':
      return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-400 dark:border-amber-900';
    default:
      return 'bg-stone-100 text-stone-600 border-stone-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700';
  }
}

export function parseAspectRatio(ratio: string): number {
  const [w, h] = ratio.split('/').map(Number);
  if (!w || !h) return 16 / 10;
  return w / h;
}

const CHANGE_TYPE_LABELS: Record<string, string> = {
  'layout-shift': 'Layout shift',
  'color-mismatch': 'Color mismatch',
  'missing-element': 'Missing element',
  'text-truncation': 'Text truncation',
  'font-substitution': 'Font substitution',
  'dynamic-content': 'Dynamic content',
};

export function formatChangeType(label: string | null | undefined): string | null {
  if (!label) return null;
  let key = label.toLowerCase().replace(/_/g, '-');
  if (key === 'insignificant-change' || key === 'meaningful-change') return null;
  
  // Merge/map consolidated categories to user-facing classifications
  if (key === 'layout-issue') key = 'layout-shift';
  if (key === 'text-issue') key = 'text-truncation';
  if (key === 'font-change') key = 'font-substitution';
  if (key === 'broken-image') key = 'missing-element';
  if (key === 'misaligned-fields') key = 'layout-shift';
  if (key === 'color-regression') key = 'color-mismatch';
  if (key === 'unreadable-text') key = 'font-substitution';
  if (key === 'overlay-obstruction') key = 'dynamic-content';
  
  return CHANGE_TYPE_LABELS[key] ?? key.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function getRunChangeLabel(run: { ai_label?: unknown; aiLabel?: unknown }): string | null {
  const raw = run.ai_label ?? run.aiLabel;
  return formatChangeType(typeof raw === 'string' ? raw : null);
}

export function changeTypeBadgeClass(label: string): string {
  let key = label.toLowerCase().replace(/_/g, '-');
  
  // Normalize/merge categories to keep the badge styles matching the classifications
  if (key === 'layout-issue') key = 'layout-shift';
  if (key === 'text-issue') key = 'text-truncation';
  if (key === 'font-change') key = 'font-substitution';
  if (key === 'broken-image') key = 'missing-element';
  if (key === 'misaligned-fields') key = 'layout-shift';
  if (key === 'color-regression') key = 'color-mismatch';
  if (key === 'unreadable-text') key = 'font-substitution';
  if (key === 'overlay-obstruction') key = 'dynamic-content';

  switch (key) {
    case 'layout-shift':
      return 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-900';
    case 'color-mismatch':
      return 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-900';
    case 'missing-element':
      return 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900';
    case 'text-truncation':
      return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900';
    case 'font-substitution':
      return 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-900';
    case 'dynamic-content':
      return 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-900';
    default:
      return 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-900';
  }
}
