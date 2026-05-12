import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { cn } from '../lib/utils';
import { TestRun } from '../types';

function normalizeSuiteName(raw: unknown) {
  const normalized = String(raw || '').replace(/\\/g, '/');
  const tail = normalized.split('/').pop() || normalized;
  return tail.replace(/\.(ya?ml|json)$/i, '');
}

export function SuiteResults() {
  const { suiteName = '' } = useParams();
  const [runs, setRuns] = React.useState<TestRun[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        const allRuns = (data.runs || []) as any[];
        const suiteRuns = allRuns
          .filter(r => normalizeSuiteName(r.suite || r.suite_name || r.file) === suiteName)
          .map((r): TestRun => {
            let status: TestRun['status'] = 'passed';
            if (r.status === 'FAIL') status = 'failed';
            if (r.decision_status === 'pending') status = 'attention';

            return {
              id: r.run,
              name: r.case_name || r.baseline_name || r.run,
              status,
              mismatch: r.mismatch_pct || 0,
              lastRun: r.decided_at || r.run,
              browser: r.browser || 'Unknown',
              device: r.device || 'Unknown',
              locale: r.locale || 'Unknown'
            };
          })
          .sort((a, b) => String(b.lastRun).localeCompare(String(a.lastRun)));

        setRuns(suiteRuns);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [suiteName]);

  if (loading) {
    return <div className="p-20 text-center text-slate-400 font-bold uppercase tracking-widest animate-pulse">Loading suite results...</div>;
  }

  return (
    <div className="p-10 max-w-6xl mx-auto">
      <header className="mb-10">
        <div className="flex items-baseline justify-between gap-6">
          <div>
            <h2 className="text-3xl font-bold tracking-tight text-on-surface dark:text-slate-100 mb-2">{suiteName}</h2>
            <p className="text-on-surface-variant dark:text-slate-400 font-medium">Suite-level execution results.</p>
          </div>
          <Link to="/summaries" className="text-xs font-bold text-primary dark:text-blue-400 hover:underline">
            Back to Summaries
          </Link>
        </div>
      </header>

      {!runs.length ? (
        <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 shadow-sm p-10 text-center">
          <p className="text-slate-500 dark:text-slate-400 font-medium">No runs found for this suite.</p>
        </div>
      ) : (
        <div className="bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 dark:bg-slate-950/50 border-b border-slate-200 dark:border-slate-800">
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Case</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Run</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Mismatch</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Status</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400">Timestamp</th>
                <th className="px-6 py-4 text-[10px] font-bold uppercase tracking-widest text-slate-500 dark:text-slate-400 text-right">Result</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {runs.map(run => (
                <tr key={run.id} className="hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                  <td className="px-6 py-4 font-semibold text-on-surface dark:text-slate-100">{run.name}</td>
                  <td className="px-6 py-4 font-mono text-sm text-on-surface-variant dark:text-slate-400">{run.id}</td>
                  <td className="px-6 py-4 font-mono text-sm font-bold text-on-surface-variant dark:text-slate-400">{run.mismatch}%</td>
                  <td className="px-6 py-4">
                    <span
                      className={cn(
                        "px-2 py-0.5 rounded text-[10px] font-bold uppercase",
                        run.status === 'passed' && "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400",
                        run.status === 'failed' && "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400",
                        run.status === 'attention' && "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400"
                      )}
                    >
                      {run.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-on-surface-variant dark:text-slate-400">{run.lastRun ? new Date(run.lastRun).toLocaleString() : 'N/A'}</td>
                  <td className="px-6 py-4 text-right">
                    <Link to={`/report/${run.id}`} className="text-xs font-bold text-primary dark:text-blue-400 hover:underline">
                      View
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

