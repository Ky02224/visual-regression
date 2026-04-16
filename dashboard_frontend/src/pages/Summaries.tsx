import React from 'react';
import { cn } from '../lib/utils';
import { Activity, TrendingUp, AlertCircle, CheckCircle2 } from 'lucide-react';
import { motion } from 'motion/react';

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

  const totalDefects = summaries.reduce((sum, batch) => sum + failedRuns(batch), 0);
  const confidenceRate = Math.round(
    summaries.reduce((sum, batch) => {
      const total = totalRuns(batch) || 1;
      return sum + (passedRuns(batch) / total) * 100;
    }, 0) / Math.max(summaries.length, 1)
  );

  return (
    <div className="p-10 max-w-6xl mx-auto">
      <header className="mb-10">
        <h2 className="text-3xl font-bold tracking-tight text-on-surface dark:text-slate-100 mb-2">Batch Summaries</h2>
        <p className="text-on-surface-variant dark:text-slate-400 font-medium">History of laboratory test runs and execution results.</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-12">
        <div className="lg:col-span-2 bg-white dark:bg-slate-900 rounded-3xl p-8 border border-slate-200 dark:border-slate-800 shadow-sm relative overflow-hidden">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100">Visual Stability Index</h3>
              <p className="text-xs text-slate-400 font-medium">Regression trends per batch</p>
            </div>
            <div className="flex items-center gap-2 px-3 py-1 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg">
              <TrendingUp className="w-3.5 h-3.5 text-emerald-600" />
              <span className="text-[10px] font-bold text-emerald-600 uppercase">Improving</span>
            </div>
          </div>
          
          <div className="h-48 w-full relative group">
            <svg viewBox="0 0 1000 200" className="w-full h-full preserve-3d">
              <defs>
                <linearGradient id="chartGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#6366f1" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="#6366f1" stopOpacity="0" />
                </linearGradient>
              </defs>
              <path 
                d={`M 0 100 ${summaries.length > 1 ? summaries.map((s, i) => `L ${(i * (1000 / (summaries.length - 1)))} ${150 - ((passedRuns(s) / (totalRuns(s) || 1)) * 100)}`).join(' ') : ''} L 1000 100`}
                fill="none" 
                stroke="#6366f1" 
                strokeWidth="3" 
                strokeLinecap="round" 
                strokeLinejoin="round"
                className="drop-shadow-lg"
              />
              <path 
                d={`M 0 100 ${summaries.map((s, i) => `L ${(i * (1000 / Math.max(summaries.length - 1, 1)))} ${150 - ((passedRuns(s) / (totalRuns(s) || 1)) * 100)}`).join(' ')} L 1000 200 L 0 200 Z`}
                fill="url(#chartGradient)"
              />
              {summaries.map((s, i) => (
                <motion.circle 
                  key={i}
                  initial={{ r: 0 }}
                  animate={{ r: 4 }}
                  cx={(i * (1000 / Math.max(summaries.length - 1, 1)))} 
                  cy={150 - ((passedRuns(s) / (totalRuns(s) || 1)) * 100)} 
                  className="fill-indigo-500 stroke-white dark:stroke-slate-900 stroke-2 hover:r-6 cursor-pointer transition-all"
                />
              ))}
            </svg>
            <div className="absolute inset-0 pointer-events-none border-b border-slate-100 dark:border-slate-800/50 flex items-end">
               <div className="w-full h-px bg-slate-100 dark:bg-slate-800/30 mb-8" />
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <DetailStatCard 
            icon={<CheckCircle2 className="w-4 h-4 text-emerald-500" />}
            label="Confidence Rate"
            value={`${confidenceRate}%`}
            sub="Avg. Pass across all batches"
          />
          <DetailStatCard 
            icon={<AlertTriangle className="w-4 h-4 text-amber-500" />}
            label="Total Defects"
            value={String(totalDefects)}
            sub="Visual anomalies detected"
          />
        </div>
      </div>

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
                <td className="px-6 py-4 font-mono text-sm font-bold text-primary dark:text-blue-400">{suiteLabel(batch)}</td>
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
function DetailStatCard({ icon, label, value, sub }: any) {
  return (
    <div className="bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200 dark:border-slate-800 shadow-sm flex items-start gap-4">
      <div className="p-2.5 bg-slate-50 dark:bg-slate-800 rounded-xl">
        {icon}
      </div>
      <div>
        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-1">{label}</p>
        <p className="text-xl font-black text-slate-900 dark:text-slate-100">{value}</p>
        <p className="text-[10px] text-slate-400 mt-1 font-medium">{sub}</p>
      </div>
    </div>
  );
}

function AlertTriangle(props: any) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </svg>
  )
}
