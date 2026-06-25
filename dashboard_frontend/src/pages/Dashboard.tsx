import React from 'react';
import { Link } from 'react-router-dom';
import { 
  History, 
  AlertTriangle, 
  CheckCircle2,
  Smartphone,
  Monitor,
  ChevronRight,
  ChevronDown,
  X,
  Globe,
  Search,
  Clock,
  RotateCcw
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { DashboardData, TestRun } from '../types';
import { useRole } from '../context/RoleContext';
import { useApiData } from '../hooks/useApiData';
import { ChangeTypeBadge } from '../components/ui/ChangeTypeBadge';
import { ReviewStatusBadge } from '../components/ui/ReviewStatusBadge';
import { normalizeReviewStatus, mismatchPctClass, reviewBorderClass, type ReviewStatus } from '../lib/reviewStatus';
import { ImageFrame } from '../components/ui/ImageFrame';
import { Button } from '../components/ui/Button';

interface GroupedRuns {
  url: string;
  runs: TestRun[];
}

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

export function Dashboard() {
  useRole();
  const { data: dashboardData, loading, error, refetch } = useApiData<DashboardData>('/api/dashboard', {
    ttl: 30000, // 30 second cache
    onError: () => {}
  });
  

  const [groupedRuns, setGroupedRuns] = React.useState<GroupedRuns[]>([]);
  
  React.useEffect(() => {
    if (!dashboardData) return;
    
    // Group runs by url
    const groups: Record<string, TestRun[]> = {};
    const runs = (dashboardData.runs || []);

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
  }, [dashboardData]);

  const [selectedRun, setSelectedRun] = React.useState<TestRun | null>(null);
  const [expandedUrls, setExpandedUrls] = React.useState<string[]>([]);
  const [previewTab, setPreviewTab] = React.useState<'current' | 'diff' | 'baseline'>('current');

  React.useEffect(() => {
    setPreviewTab('current');
  }, [selectedRun?.id]);
  


  // Filter States
  const [websiteFilter, setWebsiteFilter] = React.useState('All');
  const [deviceFilter, setDeviceFilter] = React.useState('All');
  const [localeFilter, setLocaleFilter] = React.useState('All');
  const [statusFilter, setStatusFilter] = React.useState('All');
  const [searchQuery, setSearchQuery] = React.useState('');

  // Refs & extras
  const searchRef = React.useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (e.key === '/' && tag !== 'INPUT' && tag !== 'TEXTAREA') { e.preventDefault(); searchRef.current?.focus(); }
      if (e.key === 'Escape') { setSearchQuery(''); searchRef.current?.blur(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  const toggleUrl = (url: string) => {
    setExpandedUrls(prev => 
      prev.includes(url) ? prev.filter(u => u !== url) : [...prev, url]
    );
  };

  // Derived Filter Options
  const websiteOptions = React.useMemo(() => ['All', ...new Set(groupedRuns.map(g => g.url))], [groupedRuns]);
  const deviceOptions = React.useMemo(() => ['All', ...new Set(groupedRuns.flatMap(g => g.runs.map(r => r.device)))], [groupedRuns]);
  const localeOptions = React.useMemo(() => ['All', ...new Set(groupedRuns.flatMap(g => g.runs.map(r => r.locale)))], [groupedRuns]);

  const [showAll, setShowAll] = React.useState(false);
  const LIST_LIMIT = 50;

  // Filtering Logic
  const filteredGroupedRuns = React.useMemo(() => {
    let allFiltered = groupedRuns
      .map(group => ({
        ...group,
        runs: group.runs.filter(run => {
          const q = searchQuery.toLowerCase();
          const matchesSearch = searchQuery === '' ||
                               (run.name || '').toLowerCase().includes(q) ||
                               (group.url || '').toLowerCase().includes(q);
          const matchesWebsite = websiteFilter === 'All' || group.url === websiteFilter;
          const matchesDevice = deviceFilter === 'All' || run.device === deviceFilter;
          const matchesLocale = localeFilter === 'All' || run.locale === localeFilter;
          const rs = run.reviewStatus ?? normalizeReviewStatus((run as any).review_status ?? run.status);
          const matchesStatus = statusFilter === 'All' ||
            (statusFilter === 'Changes Only' && rs !== 'no_changes') ||
            (statusFilter === 'Unreviewed' && rs === 'unreviewed') ||
            (statusFilter === 'Approved' && rs === 'approved');
          return matchesSearch && matchesWebsite && matchesDevice && matchesLocale && matchesStatus;
        })
      }))
      .filter(group => group.runs.length > 0);

    if (!showAll) {
      // Flatten, slice, and pick groups that contain those runs
      // For simplicity in this UI, we just slice the groups
      return allFiltered.slice(0, LIST_LIMIT);
    }
    return allFiltered;
  }, [groupedRuns, websiteFilter, deviceFilter, localeFilter, statusFilter, searchQuery, showAll]);

  if (loading) {
    return (
      <div className="p-8 max-w-7xl mx-auto space-y-8 animate-pulse">
        <div className="h-12 bg-slate-200/50 rounded-md w-1/4"></div>
        <div className="h-28 bg-slate-200/50 rounded-md"></div>
        <div className="h-96 bg-slate-200/50 rounded-md"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 max-w-7xl mx-auto">
        <div className="bg-red-50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 rounded-md p-6">
          <div className="flex items-start gap-4">
            <AlertTriangle className="w-6 h-6 text-red-600 dark:text-red-400 flex-shrink-0 mt-1" />
            <div className="flex-1">
              <h3 className="text-lg font-bold text-red-900 dark:text-red-200 mb-2">Failed to Load Dashboard</h3>
              <p className="text-red-700 dark:text-red-300 mb-4">{error.message}</p>
              <button
                onClick={() => refetch()}
                className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded-lg font-semibold transition-colors"
              >
                Retry
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const m = {
    baseline_count: dashboardData?.baseline_count || 0,
    run_count: dashboardData?.run_count || 0,
    pending_decisions: dashboardData?.pending_decisions || 0,
    approved_decisions: dashboardData?.approved_decisions || 0,
    ...dashboardData?.summary,
  };

  return (
    <>
    <div className="p-6 max-w-7xl mx-auto min-h-[calc(100vh-4rem)] space-y-6">
      {/* ── Stats bar ── */}
      <div className="mb-6 flex rounded-md border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden divide-x divide-slate-100 dark:divide-slate-800 shadow-sm">
        <div className="flex-1 px-8 py-6">
          <div className="flex items-center gap-2 mb-3">
            <Monitor className="w-4 h-4 text-slate-400" />
            <p className="text-xs font-semibold text-slate-400">Total runs</p>
          </div>
          <p className="text-4xl font-black tabular-nums text-slate-900 dark:text-slate-100">
            {groupedRuns.flatMap(g => g.runs).length}
          </p>
          <p className="text-xs text-slate-400 mt-1.5">Across all baselines</p>
        </div>
        <div className="flex-1 px-8 py-6">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-orange-400" />
            <p className="text-xs font-semibold text-slate-400">Unreviewed</p>
          </div>
          <p className="text-4xl font-black tabular-nums text-orange-600 dark:text-orange-400">
            {groupedRuns.flatMap(g => g.runs).filter(r => r.reviewStatus === 'unreviewed').length}
          </p>
          <p className="text-xs text-slate-400 mt-1.5">Requires action</p>
        </div>
        <div className="flex-1 px-8 py-6">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
            <p className="text-xs font-semibold text-slate-400">Passed</p>
          </div>
          <p className="text-4xl font-black tabular-nums text-emerald-600 dark:text-emerald-400">
            {groupedRuns.flatMap(g => g.runs).filter(r => r.reviewStatus === 'no_changes' || r.reviewStatus === 'approved').length}
          </p>
          <p className="text-xs text-slate-400 mt-1.5">No changes or approved</p>
        </div>
      </div>

      <div className="space-y-4">
        {/* Section header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">All Runs</h3>
            <span className="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 text-[10px] font-bold">
              {groupedRuns.flatMap(g => g.runs).length}
            </span>
          </div>
        </div>

            {/* Full-width search bar */}
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
              <input
                ref={searchRef}
                type="text"
                placeholder="Search by case name or URL…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-11 pr-12 py-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md text-sm outline-none focus:ring-2 focus:ring-accent/20 transition-all font-medium shadow-sm"
              />
              {searchQuery ? (
                <button onClick={() => setSearchQuery('')} className="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors">
                  <X className="w-3 h-3" />
                </button>
              ) : (
                <kbd className="absolute right-4 top-1/2 -translate-y-1/2 px-1.5 py-0.5 text-[9px] font-bold text-slate-300 dark:text-slate-600 bg-slate-100 dark:bg-slate-800 rounded border border-slate-200 dark:border-slate-700 pointer-events-none">/</kbd>
              )}
            </div>

            {/* Filter row */}
            <div className="flex items-center justify-between gap-3 flex-wrap">
              <div className="flex items-center gap-1.5 flex-wrap">
                {(['All', 'Changes Only', 'Unreviewed', 'Approved'] as const).map(s => (
                  <button
                    key={s}
                    onClick={() => setStatusFilter(s)}
                    className={cn(
                      "px-3 py-1.5 rounded-lg text-[10px] font-bold uppercase tracking-widest transition-all",
                      statusFilter === s
                        ? s === 'All' ? "bg-slate-900 dark:bg-white text-white dark:text-slate-900 shadow-sm"
                          : s === 'Changes Only' ? "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 border-red-200 dark:border-red-800 shadow-sm"
                          : s === 'Unreviewed' ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 border-amber-200 dark:border-amber-800 shadow-sm"
                          : "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800 shadow-sm"
                        : "bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600"
                    )}
                  >
                    {s !== 'All' && (
                      <span className={cn("mr-1 text-[8px]", statusFilter !== s && (s === 'Changes Only' ? 'text-red-400' : s === 'Unreviewed' ? 'text-orange-400' : 'text-green-400'))}>●</span>
                    )}
                    {s}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <FilterSelect label="Website" options={websiteOptions} value={websiteFilter} onChange={setWebsiteFilter} />
                <FilterSelect label="Device" options={deviceOptions} value={deviceFilter} onChange={setDeviceFilter} />
                <FilterSelect label="Locale" options={localeOptions} value={localeFilter} onChange={setLocaleFilter} />
              </div>
            </div>

            {/* Run groups */}
            <div className="grid grid-cols-1 gap-3">
              {filteredGroupedRuns.map((group) => {
                const { host, path } = parseUrl(group.url);
                return (
                  <div key={group.url} className={cn(
                    "bg-white dark:bg-slate-900 rounded-md border overflow-hidden shadow-sm transition-all",
                    group.runs.some(r => (r.reviewStatus ?? normalizeReviewStatus(r.status)) === 'rejected')
                      ? "border-slate-200 dark:border-slate-800 hover:border-red-200 dark:hover:border-red-900/50"
                      : group.runs.some(r => (r.reviewStatus ?? normalizeReviewStatus(r.status)) === 'unreviewed')
                      ? "border-slate-200 dark:border-slate-800 hover:border-orange-200 dark:hover:border-orange-900/50"
                      : "border-slate-200 dark:border-slate-800 hover:border-green-200 dark:hover:border-green-900/50"
                  )}>
                    <button
                      onClick={() => toggleUrl(group.url)}
                      className="w-full px-5 py-4 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="w-9 h-9 rounded-lg bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400 flex-shrink-0">
                          <Globe className="w-4 h-4" />
                        </div>
                        <div className="text-left min-w-0">
                          <span className="font-bold text-slate-900 dark:text-slate-100 text-sm block">{host}</span>
                          <span className="text-[11px] text-slate-400 truncate block max-w-[460px] font-mono">{path || '/'}</span>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0 ml-4">
                        {(() => {
                          const fc = group.runs.filter(r => (r.reviewStatus ?? normalizeReviewStatus(r.status)) === 'rejected').length;
                          const ac = group.runs.filter(r => (r.reviewStatus ?? normalizeReviewStatus(r.status)) === 'unreviewed').length;
                          const pc = group.runs.filter(r => (r.reviewStatus ?? normalizeReviewStatus(r.status)) === 'no_changes').length;
                          return (
                            <div className="flex items-center gap-1.5">
                              {fc > 0 && <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-[9px] font-bold"><span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse" />{fc}</span>}
                              {ac > 0 && <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-orange-50 dark:bg-orange-900/20 text-orange-600 dark:text-orange-400 text-[9px] font-bold"><span className="w-1.5 h-1.5 rounded-full bg-orange-500" />{ac}</span>}
                              {pc > 0 && <span className="flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400 text-[9px] font-bold"><span className="w-1.5 h-1.5 rounded-full bg-green-500" />{pc}</span>}
                            </div>
                          );
                        })()}
                        {expandedUrls.includes(group.url) ? <ChevronDown className="w-4 h-4 text-slate-300" /> : <ChevronRight className="w-4 h-4 text-slate-300" />}
                      </div>
                    </button>

                    <AnimatePresence>
                      {expandedUrls.includes(group.url) && (
                        <motion.div
                          initial={{ height: 0, opacity: 0 }}
                          animate={{ height: 'auto', opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }}
                          className="border-t border-slate-100 dark:border-slate-800"
                        >
                          <div className="divide-y divide-slate-50 dark:divide-slate-800/50">
                            {group.runs.map((run) => (
                              <div
                                key={run.id}
                                onClick={() => setSelectedRun(selectedRun?.id === run.id ? null : run)}
                                className={cn(
                                  "px-5 py-3.5 flex items-center justify-between cursor-pointer transition-all hover:bg-slate-50 dark:hover:bg-slate-800/30 group border-l-[3px]",
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
                                    <p className={cn("text-sm font-bold font-mono", mismatchPctClass(Number(run.mismatch)))}>
                                      {run.mismatch}%
                                    </p>
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

            {/* Empty state */}
            {filteredGroupedRuns.length === 0 && !loading && (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-16 h-16 rounded-md bg-slate-50 dark:bg-slate-800/60 flex items-center justify-center mb-5">
                  <Search className="w-8 h-8 text-slate-300 dark:text-slate-600" />
                </div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-slate-100 mb-1">No runs match your filters</h3>
                <p className="text-sm text-slate-400 max-w-xs mb-6">Try adjusting or clearing filters to see all results.</p>
                <button
                  onClick={() => { setSearchQuery(''); setStatusFilter('All'); setWebsiteFilter('All'); setDeviceFilter('All'); setLocaleFilter('All'); }}
                  className="px-5 py-2 bg-slate-900 dark:bg-white text-white dark:text-slate-900 rounded-md text-xs font-bold uppercase tracking-widest hover:opacity-80 transition-opacity"
                >
                  Clear Filters
                </button>
              </div>
            )}
          </div>
    </div>

    {/* Right-side detail drawer */}
    <AnimatePresence>
      {selectedRun && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 bg-black/20 dark:bg-black/40 z-40"
            onClick={() => setSelectedRun(null)}
          />
          <motion.div
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ type: 'spring', damping: 30, stiffness: 280 }}
            className="fixed right-0 top-16 bottom-0 w-full max-w-[520px] bg-[var(--surface)] dark:bg-slate-900 border-l border-slate-200 dark:border-slate-800 z-50 overflow-y-auto shadow-2xl"
          >
            <div className="p-6">
              <div className="flex items-start justify-between mb-5">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="px-2 py-1 bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 rounded text-[10px] font-bold uppercase tracking-widest font-mono">
                    Run {String(selectedRun.id ?? '').padStart(4, '0')}
                  </span>
                  {selectedRun.severity === 'high' && (
                    <span className="px-2 py-1 bg-red-50 text-red-600 rounded text-[10px] font-bold uppercase tracking-widest">High Priority</span>
                  )}
                  
                </div>
                <button
                  onClick={() => setSelectedRun(null)}
                  className="w-8 h-8 rounded-full hover:bg-slate-100 dark:hover:bg-slate-800 flex items-center justify-center text-slate-400 transition-colors flex-shrink-0"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
              <h3 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-1">{selectedRun.name}</h3>
              
              <div className="mb-5" />
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
              <Link to={`/report/${selectedRun.id}`}>
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

function StatCard({ icon, label, value, subValue, isAlert, variant = 'default' }: { icon: React.ReactNode, label: string, value: string, subValue: string, isAlert?: boolean, variant?: 'default' | 'success' | 'warning' | 'danger' }) {
  const valueColor = {
    default: 'text-slate-900 dark:text-white',
    success: 'text-emerald-600 dark:text-emerald-400',
    warning: 'text-orange-600 dark:text-orange-400',
    danger: 'text-red-600 dark:text-red-400',
  }[variant];

  const accentBg = {
    default: 'bg-slate-100 dark:bg-slate-800 text-slate-500',
    success: 'bg-emerald-50 dark:bg-emerald-900/20 text-emerald-600',
    warning: 'bg-orange-50 dark:bg-orange-900/20 text-orange-600',
    danger: 'bg-red-50 dark:bg-red-900/20 text-red-600',
  }[variant];

  const topBorder = {
    default: '',
    success: 'border-t-[3px] border-t-emerald-500',
    warning: isAlert ? 'border-t-[3px] border-t-orange-500' : '',
    danger: 'border-t-[3px] border-t-red-500',
  }[variant];

  return (
    <div className={cn(
      "bg-white dark:bg-slate-900 p-6 rounded-md border border-slate-200 dark:border-slate-800 transition-all hover:shadow-md group",
      topBorder,
      isAlert && 'shadow-orange-100 dark:shadow-none'
    )}>
      <div className="flex items-center justify-between mb-4">
        <span className="text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{label}</span>
        <div className={cn("w-8 h-8 rounded-lg flex items-center justify-center", accentBg)}>
          {icon}
        </div>
      </div>
      <div>
        <span className={cn("text-4xl font-bold tracking-tighter font-mono", valueColor)}>{value}</span>
        <p className="text-[11px] font-medium text-slate-400 mt-1.5">{subValue}</p>
      </div>
    </div>
  );
}

function FilterSelect({ label, options, value, onChange }: { label: string, options: string[], value: string, onChange: (val: string) => void }) {
  return (
    <div className="flex gap-2 items-center px-3 py-1.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm">
      <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400">{label}:</span>
      <select 
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border-none bg-transparent focus:ring-0 text-primary cursor-pointer p-0 pr-6 text-xs font-bold outline-none"
      >
        {options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
      </select>
    </div>
  );
}

function StatusBadge({ status }: { status: TestRun['status'] }) {
  switch (status) {
    case 'failed':
      return (
        <div className="flex items-center gap-2 px-3 py-1 bg-red-50 dark:bg-red-900/20 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-red-500" />
          <span className="text-red-600 dark:text-red-400 text-[10px] font-bold uppercase tracking-widest">Failed</span>
        </div>
      );
    case 'attention':
      return (
        <div className="flex items-center gap-2 px-3 py-1 bg-orange-50 dark:bg-orange-900/20 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-orange-500" />
          <span className="text-orange-600 dark:text-orange-400 text-[10px] font-bold uppercase tracking-widest">Attention</span>
        </div>
      );
    case 'passed':
      return (
        <div className="flex items-center gap-2 px-3 py-1 bg-green-50 dark:bg-green-900/20 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
          <span className="text-green-600 dark:text-green-400 text-[10px] font-bold uppercase tracking-widest">Passed</span>
        </div>
      );
    default:
      return null;
  }
}

function InfoItem({ label, value, valueClass }: { label: string, value: string, valueClass?: string }) {
  return (
    <div>
      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.1em] mb-1">{label}</p>
      <p className={cn("font-bold text-primary dark:text-slate-200", valueClass)}>{value}</p>
    </div>
  );
}

