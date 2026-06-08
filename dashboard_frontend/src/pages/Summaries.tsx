import React from 'react';
import { Link } from 'react-router-dom';
import { Activity } from 'lucide-react';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { Badge } from '../components/ui/Badge';
import { EmptyState } from '../components/ui/EmptyState';

function suiteLabel(batch: any) {
  const raw = batch.suite || batch.suite_name || batch.file || 'Manual Run';
  const normalized = String(raw).replace(/\\/g, '/');
  const tail = normalized.split('/').pop() || normalized;
  return tail.replace(/\.(ya?ml|json)$/i, '');
}
function totalRuns(batch: any) { return batch.total ?? batch.total_cases ?? batch.total_runs ?? 0; }
function passedRuns(batch: any) { return batch.passed ?? batch.passed_cases ?? 0; }
function failedRuns(batch: any) { return (batch.failed ?? batch.failed_cases ?? 0) + (batch.errors ?? 0); }
function batchTimestamp(batch: any): Date | null {
  const raw = batch.finished_at || batch.started_at || batch.timestamp;
  if (!raw) return null;
  if (typeof raw === 'number') return new Date(raw * 1000);
  return new Date(raw);
}

export function Summaries() {
  const [summaries, setSummaries] = React.useState<any[]>([]);
  const [loading, setLoading] = React.useState(true);
  React.useEffect(() => {
    fetch('/api/dashboard').then(res => res.json()).then(data => { setSummaries(data.recent_summaries || []); setLoading(false); }).catch(() => setLoading(false));
  }, []);
  if (loading) return <div className="p-8 max-w-6xl mx-auto"><div className="animate-shimmer h-10 w-48 rounded-md mb-6" /><div className="space-y-2">{[1,2,3].map(i => <div key={i} className="animate-shimmer h-14 rounded-md" />)}</div></div>;
  if (!summaries.length) return <div className="p-8 max-w-6xl mx-auto"><PageHeader title="Batch summaries" description="Run a batch comparison to populate this page." /><Panel><EmptyState icon={<Activity className="w-8 h-8" />} title="No batch summaries yet" description="Recent suite runs will appear here once a batch execution finishes." /></Panel></div>;
  return (
    <div className="p-8 max-w-6xl mx-auto">
      <PageHeader title="Batch summaries" description="History of batch runs and their results." />
      <Panel className="overflow-hidden p-0">
        <table className="w-full text-left border-collapse">
          <thead><tr className="border-b border-[var(--outline)] bg-stone-50 dark:bg-zinc-900/50">
            <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Suite name</th>
            <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Total runs</th>
            <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Timestamp</th>
            <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)]">Status</th>
            <th className="px-4 py-3 text-xs font-medium text-[var(--on-surface-variant)] text-center">Result</th>
          </tr></thead>
          <tbody className="divide-y divide-[var(--outline)]">
            {summaries.map((batch, index) => {
              const failed = failedRuns(batch); const passed = passedRuns(batch); const ts = batchTimestamp(batch); const allPassed = failed === 0;
              return (
                <tr key={index} className="hover:bg-stone-50 dark:hover:bg-zinc-800/40 transition-colors">
                  <td className="px-4 py-3 font-mono text-sm"><Link to={`/suite/${encodeURIComponent(suiteLabel(batch))}`} className="text-indigo-600 dark:text-indigo-400 hover:underline">{suiteLabel(batch)}</Link></td>
                  <td className="px-4 py-3 text-sm">{totalRuns(batch)}</td>
                  <td className="px-4 py-3 text-xs text-[var(--on-surface-variant)]">{ts ? ts.toLocaleString() : '—'}</td>
                  <td className="px-4 py-3"><Badge status={allPassed ? 'passed' : 'failed'}>{allPassed ? 'Passed' : 'Failed'}</Badge></td>
                  <td className="px-4 py-3 text-center text-sm font-mono"><span className="text-green-600">{passed}</span> / <span className="text-red-600">{failed}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
