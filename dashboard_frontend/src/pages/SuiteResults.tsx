import React from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { ReviewStatus, RunRowWire, SuiteSummaryWire } from '../types';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { EmptyState } from '../components/ui/EmptyState';
import { ChangeTypeBadge } from '../components/ui/ChangeTypeBadge';
import { ReviewStatusBadge } from '../components/ui/ReviewStatusBadge';
import { getRunChangeLabel } from '../lib/utils';
import { normalizeReviewStatus, mismatchPctClass } from '../lib/reviewStatus';
import { Activity, AlertTriangle } from 'lucide-react';
import { cn } from '../lib/utils';
import { useVirtualScroll } from '../hooks/useVirtualScroll';

// Below this row count, just render the plain table — the extra scroll
// container and spacer rows only pay off once a suite has enough cases
// that rendering every row at once becomes the bottleneck.
const VIRTUALIZE_THRESHOLD = 30;
const ROW_HEIGHT = 73;
const TABLE_MAX_HEIGHT = 600;

function extractRunId(reportPath: string | null | undefined): string {
  if (!reportPath) return '';
  const normalized = String(reportPath).replace(/\\/g, '/');
  const parts = normalized.split('/');
  if (parts.length >= 2) {
    return parts[parts.length - 2];
  }
  return '';
}

function normalizeSuiteName(raw: unknown) {
  const normalized = String(raw || '').replace(/\\/g, '/');
  const tail = normalized.split('/').pop() || normalized;
  return tail.replace(/\.(ya?ml|json)$/i, '');
}

interface MappedCaseRow {
  id: string;
  name: string;
  status: string;
  message: string;
  mismatch: number;
  reviewStatus: ReviewStatus | 'skipped' | 'error';
  aiLabel: string | undefined;
  ai_label: string | undefined;
  browser: string;
  device: string;
  locale: string;
  lastRun: string;
  hasRun: boolean;
}

export function SuiteResults() {
  const { suiteName = '' } = useParams();
  const [searchParams] = useSearchParams();
  const fileParam = searchParams.get('file') || '';
  const [runs, setRuns] = React.useState<MappedCaseRow[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [retryToken, setRetryToken] = React.useState(0);

  React.useEffect(() => {
    setLoading(true);
    setError(null);
    // This page can stay mounted while suiteName/fileParam change (e.g. back/
    // forward across two suite URLs already in history), so an in-flight
    // request for the previous suite must not be allowed to overwrite the
    // table with stale data if it resolves after the new suite's request.
    let cancelled = false;
    fetch('/api/dashboard')
      .then(res => {
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        return res.json();
      })
      .then((data: { recent_summaries?: SuiteSummaryWire[]; runs?: RunRowWire[] }) => {
        if (cancelled) return;
        const summaries = data.recent_summaries || [];
        let selectedSummary: SuiteSummaryWire | undefined;
        if (fileParam) {
          selectedSummary = summaries.find((s) => s.file === fileParam);
        }
        if (!selectedSummary) {
          selectedSummary = summaries.find((s) => normalizeSuiteName(s.suite || s.suite_name || s.file) === suiteName);
        }

        if (!selectedSummary) {
          setRuns([]);
          setLoading(false);
          return;
        }

        const allRuns = data.runs || [];
        const mappedCases: MappedCaseRow[] = (selectedSummary.cases || []).map((c) => {
          const runId = extractRunId(c.report);
          const matchingRun = allRuns.find(r => r.id === runId);

          return {
            id: runId || `case-${c.name}-${Math.random()}`,
            name: c.name,
            status: c.status,
            message: c.message || '',
            mismatch: matchingRun ? (matchingRun.mismatch_pct ?? matchingRun.mismatch ?? 0) : (c.mismatch_pct ?? 0),
            reviewStatus: matchingRun
              ? normalizeReviewStatus(matchingRun.review_status)
              : (c.status === 'SKIP' ? 'skipped' : c.status === 'ERROR' ? 'error' : normalizeReviewStatus(c.decision_status ?? c.status)),
            aiLabel: matchingRun ? (matchingRun.ai_label ?? matchingRun.aiLabel) : c.ai_label,
            ai_label: matchingRun ? (matchingRun.ai_label ?? matchingRun.aiLabel) : c.ai_label,
            browser: matchingRun ? matchingRun.browser : 'Unknown',
            device: matchingRun ? matchingRun.device : 'Unknown',
            locale: matchingRun ? matchingRun.locale : 'Unknown',
            lastRun: selectedSummary.finished_at || selectedSummary.started_at || '',
            hasRun: !!matchingRun && c.status !== 'SKIP' && c.status !== 'ERROR',
          };
        });

        setRuns(mappedCases);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : 'Failed to load suite results');
        setLoading(false);
      });
    return () => { cancelled = true; };
  }, [suiteName, fileParam, retryToken]);

  const shouldVirtualize = runs.length > VIRTUALIZE_THRESHOLD;
  const { visibleItems, totalHeight, onScroll, startIndex, endIndex } = useVirtualScroll(runs, {
    itemHeight: ROW_HEIGHT,
    containerHeight: TABLE_MAX_HEIGHT,
  });

  if (loading) {
    return (
      <div className="p-8 max-w-6xl mx-auto">
        <div className="animate-shimmer h-10 w-64 rounded-md mb-6" />
        <div className="space-y-2">{[1,2,3,4].map(i => <div key={i} className="animate-shimmer h-14 rounded-md" />)}</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 max-w-6xl mx-auto">
        <PageHeader title={suiteName} description="Suite-level execution results." />
        <Panel>
          <EmptyState
            icon={<AlertTriangle className="w-8 h-8 text-red-500" />}
            title="Failed to load suite results"
            description={error}
            action={
              <button
                onClick={() => setRetryToken(t => t + 1)}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg text-sm font-semibold transition-colors"
              >
                Retry
              </button>
            }
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-6xl mx-auto">
      <div className="mb-2">
        <Link to="/summaries" className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline">
          ← Back to builds
        </Link>
      </div>
      <PageHeader title={suiteName} description="Suite-level execution results." />
      {!runs.length ? (
        <Panel><EmptyState icon={<Activity className="w-8 h-8" />} title="No runs found" description="No runs were recorded for this suite." /></Panel>
      ) : (
        <Panel className="overflow-hidden p-0">
          <div
            className={shouldVirtualize ? 'overflow-y-auto' : undefined}
            style={shouldVirtualize ? { maxHeight: TABLE_MAX_HEIGHT } : undefined}
            onScroll={shouldVirtualize ? onScroll : undefined}
          >
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[var(--outline)] bg-stone-50 dark:bg-zinc-900/50">
                <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Test case</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Status</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Change type</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Mismatch</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Last run</th>
                <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--outline)]">
              {shouldVirtualize && startIndex > 0 && (
                <tr aria-hidden="true" style={{ height: startIndex * ROW_HEIGHT }}>
                  <td colSpan={6} />
                </tr>
              )}
              {(shouldVirtualize ? visibleItems.map(v => v.item) : runs).map(run => (
                <tr key={run.id} className="hover:bg-stone-50 dark:hover:bg-zinc-800/40 transition-colors">
                  <td className="px-4 py-3 text-sm font-medium">
                    <div>{run.name}</div>
                    {run.message && (
                      <div className="text-xs text-red-500 mt-1 font-medium">{run.message}</div>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {run.reviewStatus === 'skipped' ? (
                      <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border bg-stone-100 text-stone-600 border-stone-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700">
                        Skipped
                      </span>
                    ) : run.reviewStatus === 'error' ? (
                      <span className="inline-flex items-center px-2 py-0.5 text-xs font-medium rounded border bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-400 dark:border-red-900">
                        Error
                      </span>
                    ) : (
                      <ReviewStatusBadge status={run.reviewStatus} />
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {run.hasRun ? (
                      <ChangeTypeBadge label={getRunChangeLabel(run) ?? run.aiLabel} />
                    ) : (
                      <span className="text-stone-400">—</span>
                    )}
                  </td>
                  <td className={cn('px-4 py-3 font-mono text-sm', run.hasRun ? mismatchPctClass(Number(run.mismatch)) : 'text-stone-400')}>
                    {run.hasRun ? `${run.mismatch}%` : '—'}
                  </td>
                  <td className="px-4 py-3 text-xs text-[var(--on-surface-variant)]">
                    {run.lastRun ? new Date(run.lastRun).toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {run.hasRun ? (
                      <Link to={`/report/${run.id}`} state={{ from: 'suite', suiteName, file: fileParam }} className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline">
                        Review
                      </Link>
                    ) : (
                      <span className="text-stone-400 text-sm">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {shouldVirtualize && endIndex < runs.length - 1 && (
                <tr aria-hidden="true" style={{ height: totalHeight - (endIndex + 1) * ROW_HEIGHT }}>
                  <td colSpan={6} />
                </tr>
              )}
            </tbody>
          </table>
          </div>
        </Panel>
      )}
    </div>
  );
}
