import React from 'react';
import { Link } from 'react-router-dom';
import { cn } from '../lib/utils';
import { Activity } from 'lucide-react';

function suiteLabel(batch: any) {
  const raw = batch.suite || batch.suite_name || batch.file || 'Manual Run';
  const normalized = String(raw).replace(/\\/g, '/');
  const tail = normalized.split('/').pop() || normalized;
  return tail.replace(/\.(ya?ml|json)$/i, '');
}

function totalRuns(batch: any) {
  return batch.total ?? batch.total_cases ?? batch.total_runs ?? 0;
}

function passedRuns(batch: any) {
  return batch.passed ?? batch.passed_cases ?? 0;
}

function failedRuns(batch: any) {
  const hardFailed = batch.failed ?? batch.failed_cases ?? 0;
  const errorCount = batch.errors ?? 0;
  return hardFailed + errorCount;
}

function batchTimestamp(batch: any) {
  return batch.finished_at || batch.started_at || batch.timestamp || null;
}

export function Summaries() {
  const [summaries, setSummaries] = React.useState<any[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        setSummaries(data.recent_summaries || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="p-20 text-center text-slate-400 font-bold uppercase tracking-widest animate-pulse">Analyzing laboratory records...</div>;
  }

  if (!summaries.length) {
    return (
      <div className="p-10 max-w-4xl mx-auto">
        <header className="mb-10">
          <h2 className="text-3xl font-bold tracking-tight text-on-surface dark:text-slate-100 mb-2">Batch Summaries</h2>
          <p className="text-on-surface-variant dark:text-slate-400 font-medium">Run a batch comparison to populate this page with recent summary data.</p>
        </header>
        <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm p-10 text-center">
          <div className="mx-auto mb-4 w-14 h-14 rounded-2xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
            <Activity className="w-6 h-6 text-slate-500" />
          </div>
          <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-2">No batch summaries yet</h3>
          <p className="text-slate-500 dark:text-slate-400 max-w-xl mx-auto">
            Recent suite runs will appear here once a batch execution finishes and writes a summary file.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-10 max-w-6xl mx-auto">
      <header className="mb-10">
        <h2 className="text-3xl font-bold tracking-tight text-on-surface dark:text-slate-100 mb-2">Batch Summaries</h2>
        <p className="text-on-surface-variant dark:text-slate-400 font-medium">History of laboratory test runs and execution results.</p>
      </header>

      <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-slate-50 dark:bg-slate-950/50 border-b border-slate-200 dark:border-slate-800">
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Suite Name</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Total Run</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Timestamp</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Status</th>
              <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400 text-center">Result</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {summaries.map((batch, index) => (
              <tr key={index} className="hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                <td className="px-6 py-4 font-mono text-sm font-bold">
                  <Link
                    to={`/suite/${encodeURIComponent(suiteLabel(batch))}`}
                    className="text-primary dark:text-blue-400 hover:underline"
                  >
                    {suiteLabel(batch)}
                  </Link>
                </td>
                <td className="px-6 py-4 text-sm text-on-surface-variant dark:text-slate-400 font-bold">{totalRuns(batch)}</td>
                <td className="px-6 py-4 text-sm text-on-surface-variant dark:text-slate-400">{batchTimestamp(batch) ? new Date(batchTimestamp(batch)).toLocaleString() : 'N/A'}</td>
                <td className="px-6 py-4">
                  <span className={cn(
                    "px-2 py-0.5 rounded text-[10px] font-bold uppercase",
                    failedRuns(batch) === 0 ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400" : "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                  )}>
                    {failedRuns(batch) === 0 ? 'Passed' : 'Regressions'}
                  </span>
                </td>
                <td className="px-6 py-4 text-center">
                  <span className="text-sm font-bold text-on-surface dark:text-slate-200">
                    {passedRuns(batch)} / {totalRuns(batch)}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
