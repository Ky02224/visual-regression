import React from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AlertTriangle, CheckCircle2, Monitor, Globe,
  ChevronDown, ChevronRight, Search, X, Clock, GitBranch, GitCommit
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { TestRun } from '../types';
import { useApiData } from '../hooks/useApiData';
import { ChangeTypeBadge } from '../components/ui/ChangeTypeBadge';
import { ReviewStatusBadge } from '../components/ui/ReviewStatusBadge';
import { normalizeReviewStatus, mismatchPctClass, reviewBorderClass } from '../lib/reviewStatus';
import { ImageFrame } from '../components/ui/ImageFrame';
import { Button } from '../components/ui/Button';

interface GroupedRuns { url: string; runs: TestRun[]; }

function parseUrl(url: string): { host: string; path: string } {
  try {
    const u = new URL(url.startsWith('http') ? url : `https://${url}`);
    return { host: u.host, path: u.pathname + (u.search || '') };
  } catch {
    const slash = url.indexOf('/');
    if (slash !== -1) return { host: url.slice(0, slash), path: url.slice(slash) };
    return { host: url, path: '/' };
  }
}

function relativeTime(ts: string | number | null | undefined): string | null {
  if (!ts) return null;
  const d = typeof ts === 'number' ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
  if (isNaN(d.getTime())) return null;
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function BuildDetail() {
  const { buildId } = useParams<{ buildId: string }>();
  const { data: dashboardData, loading } = useApiData<any>('/api/dashboard', { ttl: 30000, onError: () => {} });

  const build = React.useMemo(() =>
    (dashboardData?.builds || []).find((b: any) => b.build_id === buildId),
    [dashboardData, buildId]
  );

  const [groupedRuns, setGroupedRuns] = React.useState<GroupedRuns[]>([]);
  const [expandedUrls, setExpandedUrls] = React.useState<string[]>([]);
  const [selectedRun, setSelectedRun] = React.useState<TestRun | null>(null);
  const [searchQuery, setSearchQuery] = React.useState('');
  const [statusFilter, setStatusFilter] = React.useState('All');
  const [previewTab, setPreviewTab] = React.useState<'current' | 'diff' | 'baseline'>('current');
  const searchRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    setPreviewTab('current');
  }, [selectedRun?.id]);

  React.useEffect(() => {
    if (!dashboardData) return;
    const runs = (dashboardData.runs || []).filter((r: any) => r.build_id === buildId);
    const groups: Record<string, TestRun[]> = {};
    runs.forEach((r: any) => {
      const urlStr = r.url || 'Unknown';
      const mapped: TestRun = {
        ...r,
        id: r.id || r.run,
        name: r.name || r.case_name || r.id,
        mismatch: Number(r.mismatch ?? r.mismatch_pct ?? 0),
        reviewStatus: normalizeReviewStatus(r.review_status ?? r.status),
        status: r.status,
        browser: r.browser || 'Unknown',
        device: r.device || 'Unknown',
        locale: r.locale || 'Unknown',
        aiLabel: r.ai_label ?? r.aiLabel,
      };
      if (!groups[urlStr]) groups[urlStr] = [];
      groups[urlStr].push(mapped);
    });
    const arr = Object.keys(groups).map(url => ({ url, runs: groups[url] }));
    setGroupedRuns(arr);
  }, [dashboardData, buildId]);

  const filteredGroups = React.useMemo(() => {
    return groupedRuns
      .map(group => ({
        ...group,
        runs: group.runs.filter(run => {
          const q = searchQuery.toLowerCase();
          const matchesSearch = !searchQuery ||
            (run.name || '').toLowerCase().includes(q) ||
            (group.url || '').toLowerCase().includes(q);
          const rs = run.reviewStatus ?? normalizeReviewStatus(run.status);
          const matchesStatus = statusFilter === 'All' ||
            (statusFilter === 'Changes Only' && rs !== 'no_changes') ||
            (statusFilter === 'Unreviewed' && rs === 'unreviewed') ||
            (statusFilter === 'Approved' && rs === 'approved');
          return matchesSearch && matchesStatus;
        })
      }))
      .filter(g => g.runs.length > 0);
  }, [groupedRuns, searchQuery, statusFilter]);

  const allRuns = groupedRuns.flatMap(g => g.runs);
  const unreviewed = allRuns.filter(r => r.reviewStatus === 'unreviewed').length;
  const passed = allRuns.filter(r => r.reviewStatus === 'no_changes' || r.reviewStatus === 'approved').length;

  if (loading) {
    return (
      <div className="p-8 max-w-7xl mx-auto space-y-6 animate-pulse">
        <div className="h-8 bg-slate-200/50 rounded w-1/3" />
        <div className="h-24 bg-slate-200/50 rounded" />
        <div className="h-64 bg-slate-200/50 rounded" />
      </div>
    );
  }

  return (
    <>
    <div className="p-6 max-w-7xl mx-auto min-h-[calc(100vh-4rem)] space-y-6">
      {/* Header */}
      <div className="pb-6 border-b border-slate-200 dark:border-slate-800">
        <Link to="/summaries" className="text-xs font-semibold text-indigo-600 dark:text-indigo-400 hover:underline mb-2 inline-block">
          ← Back to Builds
        </Link>
        <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-1">
          {build?.commit_message || 'CI Build'}
        </h2>
        <div className="flex items-center gap-3 flex-wrap mt-2">
          {build?.branch && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 dark:bg-indigo-950/40 text-indigo-600 dark:text-indigo-400 text-[11px] font-bold font-mono">
              <GitBranch className="w-3 h-3" /> {build.branch}
            </span>
          )}
          {build?.commit_sha && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 text-[11px] font-mono">
              <GitCommit className="w-3 h-3" /> {build.commit_sha.slice(0, 7)}
            </span>
          )}
          {build?.author && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              by <strong className="text-slate-700 dark:text-slate-300">{build.author}</strong>
            </span>
          )}
          {build?.created_at && (
            <span className="text-xs text-slate-400">{relativeTime(build.created_at)}</span>
          )}
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 text-[11px] font-bold">
            Reviewed: {allRuns.length - unreviewed} / {allRuns.length}
          </span>
        </div>
      </div>

      {/* Stats */}
      <div className="flex rounded-md border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden divide-x divide-slate-100 dark:divide-slate-800 shadow-sm">
        <div className="flex-1 px-8 py-6">
          <div className="flex items-center gap-2 mb-3">
            <Monitor className="w-4 h-4 text-slate-400" />
            <p className="text-xs font-semibold text-slate-400">Total snapshots</p>
          </div>
          <p className="text-4xl font-black tabular-nums text-slate-900 dark:text-slate-100">{allRuns.length}</p>
          <p className="text-xs text-slate-400 mt-1.5">In this build</p>
        </div>
        <div className="flex-1 px-8 py-6">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-orange-400" />
            <p className="text-xs font-semibold text-slate-400">Unreviewed</p>
          </div>
          <p className="text-4xl font-black tabular-nums text-orange-600 dark:text-orange-400">{unreviewed}</p>
          <p className="text-xs text-slate-400 mt-1.5">Requires action</p>
        </div>
        <div className="flex-1 px-8 py-6">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
            <p className="text-xs font-semibold text-slate-400">Passed</p>
          </div>
          <p className="text-4xl font-black tabular-nums text-emerald-600 dark:text-emerald-400">{passed}</p>
          <p className="text-xs text-slate-400 mt-1.5">No changes or approved</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Section header */}
        <div className="flex items-center gap-3">
          <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">Visual Snapshots</h3>
          <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 text-[10px] font-bold">
            {allRuns.length}
          </span>
        </div>

        {/* Search */}
        <div className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
          <input
            ref={searchRef}
            type="text"
            placeholder="Search by case name or URL…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="w-full pl-11 pr-12 py-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md text-sm outline-none focus:ring-2 focus:ring-accent/20 transition-all font-medium shadow-sm"
          />
          {searchQuery && (
            <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400 hover:text-slate-600 transition-colors">
              <X className="w-3 h-3" />
            </button>
          )}
        </div>

        {/* Status filters */}
        <div className="flex items-center gap-1.5 flex-wrap">
          {(['All', 'Changes Only', 'Unreviewed', 'Approved'] as const).map(s => (
            <button
              key={s}
              onClick={() => setStatusFilter(s)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all",
                statusFilter === s
                  ? s === 'All' ? "bg-slate-900 dark:bg-white text-white dark:text-slate-900 shadow-sm"
                    : s === 'Changes Only' ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 shadow-sm"
                    : s === 'Unreviewed' ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 shadow-sm"
                    : "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 shadow-sm"
                  : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 hover:border-slate-300"
              )}
            >
              {s !== 'All' && <span className={cn("mr-1 text-[8px]", statusFilter !== s && (s === 'Changes Only' ? 'text-red-400' : s === 'Unreviewed' ? 'text-orange-400' : 'text-green-400'))}>●</span>}
              {s}
            </button>
          ))}
        </div>

        {/* Run groups */}
        <div className="grid grid-cols-1 gap-3">
          {filteredGroups.map(group => {
            const { host, path } = parseUrl(group.url);
            const isExpanded = expandedUrls.includes(group.url);

            const fc = group.runs.filter(r => (r.reviewStatus ?? normalizeReviewStatus(r.status)) === 'rejected').length;
            const ac = group.runs.filter(r => (r.reviewStatus ?? normalizeReviewStatus(r.status)) === 'unreviewed').length;
            const pc = group.runs.filter(r => {
              const rs = r.reviewStatus ?? normalizeReviewStatus(r.status);
              return rs === 'no_changes' || rs === 'approved';
            }).length;

            return (
              <div
                key={group.url}
                className={cn(
                  "bg-white dark:bg-slate-900 rounded-md border overflow-hidden shadow-sm transition-all border-l-[4px]",
                  fc > 0
                    ? "border-slate-200 dark:border-slate-800 hover:border-red-200 dark:hover:border-red-900/50 border-l-red-500"
                    : ac > 0
                    ? "border-slate-200 dark:border-slate-800 hover:border-orange-200 dark:hover:border-orange-900/50 border-l-orange-500"
                    : "border-slate-200 dark:border-slate-800 hover:border-green-200 dark:hover:border-green-900/50 border-l-green-500"
                )}
              >
                <button
                  onClick={() => setExpandedUrls(prev => isExpanded ? prev.filter(u => u !== group.url) : [...prev, group.url])}
                  className="w-full px-5 py-4 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={cn(
                      "w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0",
                      fc > 0
                        ? "bg-red-50 dark:bg-red-950/30 text-red-500"
                        : ac > 0
                        ? "bg-orange-50 dark:bg-orange-950/30 text-orange-500"
                        : "bg-green-50 dark:bg-green-950/30 text-green-500"
                    )}>
                      <Globe className="w-4 h-4" />
                    </div>
                    <div className="text-left min-w-0">
                      <span className="font-bold text-slate-900 dark:text-slate-100 text-sm block">{host}</span>
                      <span className="text-[11px] text-slate-400 truncate block max-w-[460px] font-mono">{path || '/'}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0 ml-4">
                    <div className="flex items-center gap-1.5">
                      {fc > 0 && (
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-[9px] font-bold">
                          <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />
                          {fc} failed
                        </span>
                      )}
                      {ac > 0 && (
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400 text-[9px] font-bold">
                          <span className="w-1.5 h-1.5 rounded-full bg-orange-500" />
                          {ac} changes
                        </span>
                      )}
                      {pc > 0 && (
                        <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400 text-[9px] font-bold">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
                          {pc} passed
                        </span>
                      )}
                    </div>
                    {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-300" /> : <ChevronRight className="w-4 h-4 text-slate-300" />}
                  </div>
                </button>

                <AnimatePresence>
                  {isExpanded && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      className="border-t border-slate-100 dark:border-slate-800"
                    >
                      <div className="divide-y divide-slate-50 dark:divide-slate-800/50">
                        {group.runs.map(run => (
                          <div
                            key={run.id}
                            onClick={() => setSelectedRun(selectedRun?.id === run.id ? null : run)}
                            className={cn(
                              "px-5 py-3.5 flex items-center justify-between cursor-pointer transition-all hover:bg-slate-50 dark:hover:bg-slate-800/30 border-l-[3px]",
                              selectedRun?.id === run.id
                                ? "bg-blue-50/50 dark:bg-slate-800/60 border-l-accent"
                                : reviewBorderClass(run.reviewStatus ?? normalizeReviewStatus(run.status))
                            )}
                          >
                            <div className="flex items-center gap-3 min-w-0 flex-1">
                              <div className="w-14 shrink-0 rounded-md overflow-hidden border border-[var(--outline)]">
                                <ImageFrame src={`/artifacts/${run.id}/current.png`} alt="" aspectRatio="16/10" />
                              </div>
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <p className="font-semibold text-slate-900 dark:text-slate-200 text-sm truncate">{run.name}</p>
                                  <ChangeTypeBadge label={(run as any).ai_label ?? run.aiLabel} />
                                </div>
                                <p className="text-[10px] text-slate-400 font-medium">{run.browser} · {run.device}</p>
                              </div>
                            </div>
                            <div className="flex items-center gap-3 flex-shrink-0">
                              {relativeTime((run as any).timestamp || (run as any).created_at) && (
                                <span className="hidden md:flex items-center gap-1 text-[10px] text-slate-400 font-medium">
                                  <Clock className="w-3 h-3" />{relativeTime((run as any).timestamp || (run as any).created_at)}
                                </span>
                              )}
                              <div className="text-right">
                                <p className={cn("text-sm font-bold font-mono", mismatchPctClass(Number(run.mismatch)))}>{run.mismatch}%</p>
                                <p className="text-[9px] text-slate-400 uppercase font-bold tracking-tight">Mismatch</p>
                              </div>
                              <ReviewStatusBadge status={run.reviewStatus ?? normalizeReviewStatus(run.status)} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            );
          })}
        </div>

        {filteredGroups.length === 0 && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <Search className="w-12 h-12 text-slate-200 dark:text-slate-700 mb-4" />
            <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100 mb-1">No snapshots found</h3>
            <p className="text-sm text-slate-400 max-w-xs">This build has no recorded runs, or they don't match your filters.</p>
          </div>
        )}
      </div>
    </div>

    {/* Slide-in drawer */}
    <AnimatePresence>
      {selectedRun && (
        <>
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/20 dark:bg-black/40 z-40"
            onClick={() => setSelectedRun(null)}
          />
          <motion.div
            initial={{ x: '100%' }} animate={{ x: 0 }} exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 280 }}
            className="fixed right-0 top-16 bottom-0 w-full max-w-[520px] bg-[var(--surface)] dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 z-50 overflow-y-auto shadow-2xl"
          >
            <div className="p-6">
              <div className="flex items-start justify-between mb-5">
                <span className="px-2 py-1 bg-slate-100 dark:bg-slate-800 text-slate-500 rounded text-[10px] font-bold uppercase tracking-widest font-mono">
                  Run {String(selectedRun.id ?? '').padStart(4, '0')}
                </span>
                <button onClick={() => setSelectedRun(null)} className="w-8 h-8 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-center text-slate-400 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>
              <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-4">{selectedRun.name}</h3>
              <div className="flex flex-wrap items-center gap-2 mb-4">
                <ChangeTypeBadge label={(selectedRun as any).ai_label ?? selectedRun.aiLabel} />
                <ReviewStatusBadge status={selectedRun.reviewStatus ?? normalizeReviewStatus(selectedRun.status)} />
              </div>
              <div className="flex rounded-md bg-stone-100 dark:bg-zinc-800 p-0.5 mb-3">
                {(['baseline', 'current', 'diff'] as const).map(tab => (
                  <button
                    key={tab}
                    type="button"
                    onClick={() => setPreviewTab(tab)}
                    className={cn(
                      "flex-1 text-center py-1 rounded text-xs font-semibold capitalize transition-all",
                      previewTab === tab
                        ? "bg-white dark:bg-zinc-700 shadow-sm text-slate-900 dark:text-white"
                        : "text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-300"
                    )}
                  >
                    {tab}
                  </button>
                ))}
              </div>
              <div className="rounded-md overflow-hidden border border-[var(--outline)] mb-4">
                <ImageFrame 
                  src={`/artifacts/${selectedRun.id}/${previewTab === 'diff' ? 'diff_overlay' : previewTab}.png`} 
                  alt={`${previewTab} preview`} 
                  aspectRatio="16/10" 
                />
              </div>
              <div className="flex items-center justify-between text-sm mb-4 px-1">
                <span className="text-[var(--on-surface-variant)]">Mismatch</span>
                <span className={cn("font-mono font-semibold", mismatchPctClass(Number(selectedRun.mismatch)))}>{selectedRun.mismatch}%</span>
              </div>
              <div className="grid grid-cols-2 gap-3 text-sm mb-6 px-1">
                <div><p className="text-xs text-[var(--on-surface-variant)]">Browser</p><p className="font-medium">{selectedRun.browser}</p></div>
                <div><p className="text-xs text-[var(--on-surface-variant)]">Device</p><p className="font-medium">{selectedRun.device}</p></div>
              </div>
              <Link to={`/report/${selectedRun.id}`} state={{ from: 'build', buildId }}>
                <Button variant="primary" size="lg" className="w-full">Open review</Button>
              </Link>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
    </>
  );
}
