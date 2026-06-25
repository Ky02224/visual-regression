import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { TestRun } from '../types';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { EmptyState } from '../components/ui/EmptyState';
import { ChangeTypeBadge } from '../components/ui/ChangeTypeBadge';
import { ReviewStatusBadge } from '../components/ui/ReviewStatusBadge';
import { getRunChangeLabel } from '../lib/utils';
import { normalizeReviewStatus, mismatchPctClass } from '../lib/reviewStatus';
import { Activity } from 'lucide-react';
import { cn } from '../lib/utils';

function parseRunDirDate(runId: string): string {
  const m = String(runId || '').match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
  if (!m) return '';
  return `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}`;
}

function normalizeSuiteName(raw: unknown) {
  const normalized = String(raw || '').replace(/\\/g, '/');
  const tail = normalized.split('/').pop() || normalized;
  return tail.replace(/\.(ya?ml|json)$/i, '');
}

export function SuiteResults() {
  const { suiteName = '' } = useParams();
  const [runs, setRuns] = React.useState<(TestRun & { aiLabel?: string })[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        const allRuns = (data.runs || []) as any[];
        const suiteRuns = allRuns
          .filter(r => normalizeSuiteName(r.suite || r.suite_name || r.file) === suiteName)
          .map((r): TestRun & { aiLabel?: string } => {
            return {
              id: r.run,
              name: r.case_name || r.baseline_name || r.run,
              status: r.status,
              reviewStatus: normalizeReviewStatus(r.review_status ?? r.status),
              mismatch: r.mismatch_pct || 0,
              lastRun: r.decided_at
                ? (typeof r.decided_at === 'number' ? new Date(r.decided_at * 1000).toISOString() : r.decided_at)
                : parseRunDirDate(r.run),
              browser: r.browser || 'Unknown',
              device: r.device || 'Unknown',
              locale: r.locale || 'Unknown',
              aiLabel: r.ai_label || r.aiLabel,
            };
          })
          .sort((a, b) => String(b.lastRun).localeCompare(String(a.lastRun)));
        setRuns(suiteRuns);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [suiteName]);

  if (loading) {
    return (
      <div className="p-8 max-w-6xl mx-auto">
        <div className="animate-shimmer h-10 w-64 rounded-md mb-6" />
        <div className="space-y-2">{[1,2,3,4].map(i => <div key={i} className="animate-shimmer h-14 rounded-md" />)}</div>
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
              {runs.map(run => (
                <tr key={run.id} className="hover:bg-stone-50 dark:hover:bg-zinc-800/40 transition-colors">
                  <td className="px-4 py-3 text-sm font-medium">{run.name}</td>
                  <td className="px-4 py-3"><ReviewStatusBadge status={run.reviewStatus ?? normalizeReviewStatus(run.status)} /></td>
                  <td className="px-4 py-3"><ChangeTypeBadge label={getRunChangeLabel(run as any) ?? run.aiLabel} /></td>
                  <td className={cn('px-4 py-3 font-mono text-sm', mismatchPctClass(Number(run.mismatch)))}>{run.mismatch}%</td>
                  <td className="px-4 py-3 text-xs text-[var(--on-surface-variant)]">{new Date(run.lastRun).toLocaleString()}</td>
                  <td className="px-4 py-3 text-right"><Link to={`/report/${run.id}`} state={{ from: 'suite', suiteName }} className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline">Review</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </div>
  );
}
