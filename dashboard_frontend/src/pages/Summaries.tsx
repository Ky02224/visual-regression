import React from 'react';
import { Link } from 'react-router-dom';
import { Activity, GitBranch, Layers, ChevronDown, ChevronRight, AlertTriangle } from 'lucide-react';
import { PageHeader } from '../components/ui/PageHeader';
import { Panel } from '../components/ui/Panel';
import { Badge } from '../components/ui/Badge';
import { EmptyState } from '../components/ui/EmptyState';
import { CIBuildWire, SuiteSummaryWire } from '../types';
import { relativeTime as relativeTimeOrNull } from '../lib/format';

// ── helpers ──────────────────────────────────────────────────────────────────

function relativeTime(ts: string | number | null | undefined): string {
  return relativeTimeOrNull(ts) ?? '—';
}

function suiteLabel(batch: SuiteSummaryWire) {
  const raw = batch.suite || batch.suite_name || batch.file || 'Manual Run';
  const normalized = String(raw).replace(/\\/g, '/');
  const tail = normalized.split('/').pop() || normalized;
  return tail.replace(/\.(ya?ml|json)$/i, '');
}

// ── unified entry type ───────────────────────────────────────────────────────

interface BuildEntry {
  id: string;
  source: 'ci' | 'suite';
  label: string;
  sublabel: string;
  passed: number;
  failed: number;
  total: number;
  status: 'passed' | 'failed';
  time: string;
  link: string | null;
}

function fromCIBuild(b: CIBuildWire): BuildEntry {
  const passed = b.passed_count || 0;
  const failed = b.failed_count || 0;
  const total = b.total_count || 0;
  return {
    id: b.build_id,
    source: 'ci',
    label: b.commit_message || 'CI run',
    sublabel: [b.branch, b.commit_sha?.slice(0, 7)].filter(Boolean).join(' · '),
    passed,
    failed,
    total,
    status: b.status === 'passed' ? 'passed' : 'failed',
    time: relativeTime(b.created_at),
    link: b.build_id ? `/build/${encodeURIComponent(b.build_id)}` : null,
  };
}

function fromSuiteBatch(b: SuiteSummaryWire): BuildEntry {
  const passed = b.passed ?? b.passed_cases ?? 0;
  const failed = (b.failed ?? b.failed_cases ?? 0) + (b.errors ?? 0);
  const total = b.total ?? b.total_cases ?? b.total_runs ?? 0;
  const name = suiteLabel(b);
  return {
    id: `suite-${name}-${b.finished_at || b.started_at || Math.random()}`,
    source: 'suite',
    label: name,
    sublabel: 'Suite run',
    passed,
    failed,
    total,
    status: failed === 0 ? 'passed' : 'failed',
    time: relativeTime(b.finished_at || b.started_at || b.timestamp),
    link: `/suite/${encodeURIComponent(name)}${b.file ? `?file=${encodeURIComponent(b.file)}` : ''}`,
  };
}

interface GroupedBuilds {
  key: string;
  source: 'ci' | 'suite';
  title: string;
  subtitle: string;
  passed: number;
  failed: number;
  total: number;
  status: 'passed' | 'failed';
  items: BuildEntry[];
}

// ── component ────────────────────────────────────────────────────────────────

export function Summaries() {
  const [entries, setEntries] = React.useState<BuildEntry[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [retryToken, setRetryToken] = React.useState(0);
  const [expandedGroups, setExpandedGroups] = React.useState<string[]>([]);

  React.useEffect(() => {
    setLoading(true);
    setError(null);
    fetch('/api/dashboard')
      .then(res => {
        if (!res.ok) throw new Error(`Request failed (${res.status})`);
        return res.json();
      })
      .then((data: { builds?: CIBuildWire[]; recent_summaries?: SuiteSummaryWire[] }) => {
        const ciBuilds: BuildEntry[] = (data.builds || []).map(fromCIBuild);
        const suiteBuilds: BuildEntry[] = (data.recent_summaries || []).map(fromSuiteBatch);
        const all = [...ciBuilds, ...suiteBuilds];
        setEntries(all);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to load builds');
        setLoading(false);
      });
  }, [retryToken]);

  const groups = React.useMemo(() => {
    const map: { [key: string]: BuildEntry[] } = {};
    entries.forEach(entry => {
      const groupKey = entry.source === 'ci' ? (entry.sublabel || 'CI Runs') : `Suite: ${entry.label}`;
      if (!map[groupKey]) {
        map[groupKey] = [];
      }
      map[groupKey].push(entry);
    });

    return Object.entries(map).map(([key, items]): GroupedBuilds => {
      const totalPassed = items.reduce((acc, item) => acc + item.passed, 0);
      const totalFailed = items.reduce((acc, item) => acc + item.failed, 0);
      const totalCount = items.reduce((acc, item) => acc + item.total, 0);
      const hasFail = items.some(item => item.status === 'failed');
      const source = items[0].source;

      return {
        key,
        source,
        title: source === 'ci' ? key : items[0].label,
        subtitle: source === 'ci' ? 'CI Commits' : 'Local Suite Run History',
        passed: totalPassed,
        failed: totalFailed,
        total: totalCount,
        status: hasFail ? 'failed' : 'passed',
        items: items
      };
    });
  }, [entries]);

  const toggleGroup = (key: string) => {
    setExpandedGroups(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
    );
  };

  if (loading) {
    return (
      <div className="p-8 max-w-6xl mx-auto space-y-3">
        <div className="animate-shimmer h-10 w-48 rounded-md mb-6" />
        {[1, 2, 3].map(i => <div key={i} className="animate-shimmer h-16 rounded-md" />)}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 max-w-6xl mx-auto">
        <PageHeader title="Builds" description="All test runs — suite executions and CI builds." />
        <Panel>
          <EmptyState
            icon={<AlertTriangle className="w-8 h-8 text-red-500" />}
            title="Failed to load builds"
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

  if (!entries.length) {
    return (
      <div className="p-8 max-w-6xl mx-auto">
        <PageHeader title="Builds" description="All test runs — suite executions and CI builds." />
        <Panel>
          <EmptyState
            icon={<Activity className="w-8 h-8" />}
            title="No builds yet"
            description="Run a suite or connect CI to see grouped results here."
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <PageHeader title="Builds" description="All test runs grouped by branch/commit or suite." />

      {groups.map((group) => {
        const isExpanded = expandedGroups.includes(group.key);
        return (
          <div key={group.key} className="panel overflow-hidden border border-[var(--outline)] bg-[var(--surface)] shadow-sm">
            {/* Accordion Header */}
            <div
              onClick={() => toggleGroup(group.key)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  toggleGroup(group.key);
                }
              }}
              role="button"
              tabIndex={0}
              aria-expanded={isExpanded}
              className="flex items-center justify-between gap-4 px-5 py-4 cursor-pointer select-none bg-stone-50/70 dark:bg-zinc-900/40 hover:bg-stone-50 dark:hover:bg-zinc-900 transition-colors border-b border-[var(--outline)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-inset"
            >
              <div className="flex items-center gap-3 min-w-0">
                {isExpanded ? <ChevronDown className="w-4 h-4 text-stone-400" /> : <ChevronRight className="w-4 h-4 text-stone-400" />}
                {group.source === 'ci' ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 text-[10px] font-bold shrink-0">
                    <GitBranch className="w-3 h-3" /> CI Group
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 dark:bg-zinc-800 text-slate-600 dark:text-slate-400 text-[10px] font-bold shrink-0">
                    <Layers className="w-3 h-3" /> Suite Group
                  </span>
                )}
                <h3 className="text-sm font-semibold truncate text-[var(--on-surface)]">{group.title}</h3>
                <span className="text-[11px] text-[var(--on-surface-variant)] hidden sm:inline">({group.subtitle})</span>
              </div>

              <div className="flex items-center gap-4 shrink-0">
                {/* Aggregated progress bar */}
                {group.total > 0 && (
                  <div className="hidden md:flex items-center gap-2">
                    <div className="w-24 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-emerald-500 transition-all"
                        style={{ width: `${Math.round((group.passed / group.total) * 100)}%` }}
                      />
                    </div>
                    <span className="text-[10px] font-bold text-[var(--on-surface-variant)]">
                      {Math.round((group.passed / group.total) * 100)}%
                    </span>
                  </div>
                )}
                <div className="text-xs font-mono">
                  <span className="text-emerald-600 dark:text-emerald-400 font-bold">{group.passed}</span>
                  <span className="text-stone-400 mx-0.5">/</span>
                  <span className="text-red-600 dark:text-red-400 font-bold">{group.failed}</span>
                  <span className="text-stone-400 text-[10px] ml-1">passed</span>
                </div>
                <Badge status={group.status === 'passed' ? 'passed' : 'failed'}>
                  {group.status === 'passed' ? 'Passed' : 'Failed'}
                </Badge>
              </div>
            </div>

            {/* Accordion Body */}
            {isExpanded && (
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse">
                  <thead>
                    <tr className="border-b border-[var(--outline)] bg-stone-50/30 dark:bg-zinc-900/10">
                      <th className="px-5 py-2.5 text-xs font-semibold text-[var(--on-surface-variant)]">Execution Name</th>
                      <th className="px-5 py-2.5 text-xs font-semibold text-[var(--on-surface-variant)]">Tests Details</th>
                      <th className="px-5 py-2.5 text-xs font-semibold text-[var(--on-surface-variant)]">Result</th>
                      <th className="px-5 py-2.5 text-xs font-semibold text-[var(--on-surface-variant)]">Executed</th>
                      <th className="px-5 py-2.5 text-xs font-semibold text-[var(--on-surface-variant)]">Completion Progress</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--outline)]">
                    {group.items.map((entry) => (
                      <tr key={entry.id} className="hover:bg-stone-50/50 dark:hover:bg-zinc-800/20 transition-colors">
                        <td className="px-5 py-3 max-w-xs">
                          {entry.link ? (
                            <Link to={entry.link} className="font-semibold text-sm text-indigo-600 dark:text-indigo-400 hover:underline truncate block">
                              {entry.label}
                            </Link>
                          ) : (
                            <p className="font-semibold text-sm text-[var(--on-surface)] truncate">{entry.label}</p>
                          )}
                          {entry.sublabel && entry.source === 'suite' && (
                            <p className="text-[10px] text-[var(--on-surface-variant)] font-mono mt-0.5">{entry.sublabel}</p>
                          )}
                        </td>
                        <td className="px-5 py-3 text-xs font-mono">
                          <span className="text-emerald-600 dark:text-emerald-400 font-bold">{entry.passed}</span>
                          <span className="text-[var(--on-surface-variant)] mx-1">/</span>
                          <span className="text-red-600 dark:text-red-400 font-bold">{entry.failed}</span>
                          <span className="text-[10px] text-[var(--on-surface-variant)] ml-1">of {entry.total}</span>
                        </td>
                        <td className="px-5 py-3">
                          <Badge status={entry.status === 'passed' ? 'passed' : 'failed'}>
                            {entry.status === 'passed' ? 'Passed' : 'Failed'}
                          </Badge>
                        </td>
                        <td className="px-5 py-3 text-xs text-[var(--on-surface-variant)]">{entry.time}</td>
                        <td className="px-5 py-3">
                          {entry.total > 0 && (
                            <div className="flex items-center gap-2">
                              <div className="w-20 h-1 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                                <div
                                  className="h-full rounded-full bg-emerald-500 transition-all"
                                  style={{ width: `${Math.round((entry.passed / entry.total) * 100)}%` }}
                                />
                              </div>
                              <span className="text-[10px] font-bold text-[var(--on-surface-variant)]">
                                {Math.round((entry.passed / entry.total) * 100)}%
                              </span>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
