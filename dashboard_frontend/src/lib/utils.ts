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
  'color-regression': 'Color change',
  'missing-element': 'Missing element',
  'text-truncation': 'Text truncation',
  'overlay-obstruction': 'Overlay obstruction',
  'broken-image': 'Broken image',
  'misaligned-fields': 'Misaligned fields',
  'unreadable-text': 'Unreadable text',
};

export function formatChangeType(label: string | null | undefined): string | null {
  if (!label) return null;
  const key = label.toLowerCase().replace(/_/g, '-');
  if (key === 'insignificant-change' || key === 'meaningful-change') return null;
  return CHANGE_TYPE_LABELS[key] ?? label.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

export function getRunChangeLabel(run: Record<string, unknown>): string | null {
  const raw = run.ai_label ?? run.aiLabel;
  return formatChangeType(typeof raw === 'string' ? raw : null);
}

export function changeTypeBadgeClass(label: string): string {
  const key = label.toLowerCase().replace(/_/g, '-');
  switch (key) {
    case 'layout-shift':
    case 'misaligned-fields':
      return 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-900';
    case 'color-regression':
      return 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-900';
    case 'missing-element':
    case 'broken-image':
      return 'bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900';
    case 'text-truncation':
    case 'unreadable-text':
      return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900';
    case 'overlay-obstruction':
      return 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-900';
    default:
      return 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-900';
  }
}
