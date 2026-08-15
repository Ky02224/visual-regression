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
import { useDebounce } from '../hooks/useDebounce';
import { useGroupedRuns } from '../hooks/useGroupedRuns';
import { ChangeTypeBadge } from '../components/ui/ChangeTypeBadge';
import { ReviewStatusBadge } from '../components/ui/ReviewStatusBadge';
import { CommentCountBadge } from '../components/ui/CommentCountBadge';
import { normalizeReviewStatus, mismatchPctClass, reviewBorderClass, type ReviewStatus } from '../lib/reviewStatus';
import { parseUrl, relativeTime } from '../lib/format';
import { ImageFrame } from '../components/ui/ImageFrame';
import { Button } from '../components/ui/Button';
import { api } from '../services/apiClient';

export function Dashboard() {
  const { can } = useRole();
  const { data: dashboardData, loading, error, refetch } = useApiData<DashboardData>('/api/dashboard', {
    ttl: 30000, // 30 second cache
    onError: () => {}
  });
  

  const groupedRuns = useGroupedRuns(dashboardData?.runs);

  const [selectedRun, setSelectedRun] = React.useState<TestRun | null>(null);
  const [expandedUrls, setExpandedUrls] = React.useState<string[]>([]);
  const [previewTab, setPreviewTab] = React.useState<'current' | 'diff' | 'baseline'>('current');
  const [selectedRunsForBulk, setSelectedRunsForBulk] = React.useState<string[]>([]);
  const [pendingBulkDecision, setPendingBulkDecision] = React.useState<'approved' | 'rejected' | null>(null);
  const [bulkError, setBulkError] = React.useState<string | null>(null);

  const handleBulkReview = React.useCallback(async (decision: 'approved' | 'rejected') => {
    if (!can('approve')) return;
    if (selectedRunsForBulk.length === 0) return;
    setBulkError(null);
    try {
      const result = await api.post<{ ok: boolean; error?: string }>('/api/bulk-review', {
        runs: selectedRunsForBulk,
        decision,
        reviewer: 'dashboard_ui'
      });
      if (result.ok) {
        setSelectedRunsForBulk([]);
        refetch();
      } else {
        setBulkError(result.error || 'Failed to submit bulk review');
      }
    } catch (e) {
      setBulkError('Error submitting bulk review: ' + String(e));
    }
  }, [selectedRunsForBulk, refetch, can]);

  const confirmBulkReview = React.useCallback(() => {
    if (!pendingBulkDecision) return;
    handleBulkReview(pendingBulkDecision);
    setPendingBulkDecision(null);
  }, [pendingBulkDecision, handleBulkReview]);

  React.useEffect(() => {
    setPreviewTab('current');
  }, [selectedRun?.id]);
  


  // Filter States
  const [websiteFilter, setWebsiteFilter] = React.useState('All');
  const [deviceFilter, setDeviceFilter] = React.useState('All');
  const [localeFilter, setLocaleFilter] = React.useState('All');
  const [statusFilter, setStatusFilter] = React.useState('All');
  const [searchQuery, setSearchQuery] = React.useState('');
  const debouncedSearchQuery = useDebounce(searchQuery, 150);

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
  const allFilteredGroupedRuns = React.useMemo(() => {
    return groupedRuns
      .map(group => ({
        ...group,
        runs: group.runs.filter(run => {
          const q = debouncedSearchQuery.toLowerCase();
          const matchesSearch = debouncedSearchQuery === '' ||
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
  }, [groupedRuns, websiteFilter, deviceFilter, localeFilter, statusFilter, debouncedSearchQuery]);

  // Reset the truncated view whenever the filters materially change the result set,
  // so "Show all" from a previous filter doesn't silently carry over.
  React.useEffect(() => {
    setShowAll(false);
  }, [websiteFilter, deviceFilter, localeFilter, statusFilter, debouncedSearchQuery]);

  const filteredGroupedRuns = React.useMemo(() => {
    if (!showAll) {
      // Flatten, slice, and pick groups that contain those runs
      // For simplicity in this UI, we just slice the groups
      return allFilteredGroupedRuns.slice(0, LIST_LIMIT);
    }
    return allFilteredGroupedRuns;
  }, [allFilteredGroupedRuns, showAll]);

  const totalFilteredRunCount = React.useMemo(
    () => allFilteredGroupedRuns.flatMap(g => g.runs).length,
    [allFilteredGroupedRuns]
  );
  const isTruncated = !showAll && allFilteredGroupedRuns.length > LIST_LIMIT;

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
    run_count: dashboardData?.runs?.length || 0,
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
              {totalFilteredRunCount}
            </span>
            {isTruncated && (
              <span className="text-[10px] text-slate-400 dark:text-slate-500">
                showing first {LIST_LIMIT} groups —{' '}
                <button
                  onClick={() => setShowAll(true)}
                  className="text-accent hover:underline font-semibold cursor-pointer"
                >
                  show all
                </button>
              </span>
            )}
          </div>
        </div>

            {/* Full-width search bar */}
            <div className="relative">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400 pointer-events-none" />
              <input
                ref={searchRef}
                type="text"
                aria-label="Search by case name or URL"
                placeholder="Search by case name or URL…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-11 pr-12 py-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-md text-sm outline-none focus:ring-2 focus:ring-accent/20 transition-all font-medium shadow-sm"
              />
              {searchQuery ? (
                <button onClick={() => setSearchQuery('')} aria-label="Clear search" className="absolute right-3 top-1/2 -translate-y-1/2 w-6 h-6 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors">
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
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter' || e.key === ' ') {
                                    e.preventDefault();
                                    setSelectedRun(selectedRun?.id === run.id ? null : run);
                                  }
                                }}
                                role="button"
                                tabIndex={0}
                                aria-pressed={selectedRun?.id === run.id}
                                className={cn(
                                  "px-5 py-3.5 flex items-center justify-between cursor-pointer transition-all hover:bg-slate-50 dark:hover:bg-slate-800/30 group border-l-[3px] focus-visible:outline-none focus-visible:bg-slate-50 dark:focus-visible:bg-slate-800/30",
                                  selectedRun?.id === run.id
                                    ? "bg-blue-50/50 dark:bg-slate-800/60 border-l-accent"
                                    : reviewBorderClass(run.reviewStatus ?? normalizeReviewStatus(run.status))
                                )}
                              >
                                <div className="flex items-center gap-3 min-w-0 flex-1">
                                  <input
                                    type="checkbox"
                                    aria-label={`Select ${run.name} for bulk review`}
                                    checked={selectedRunsForBulk.includes(run.id)}
                                    onClick={(e) => e.stopPropagation()}
                                    onChange={(e) => {
                                      if (e.target.checked) {
                                        setSelectedRunsForBulk(prev => [...prev, run.id]);
                                      } else {
                                        setSelectedRunsForBulk(prev => prev.filter(id => id !== run.id));
                                      }
                                    }}
                                    className="w-4 h-4 rounded border-slate-300 dark:border-slate-700 text-accent focus:ring-accent cursor-pointer mr-1"
                                  />
                                  <div className="w-14 shrink-0 rounded-md overflow-hidden border border-[var(--outline)]">
                                    <ImageFrame src={`/artifacts/${run.id}/current.webp`} alt={`Current snapshot for ${run.name}`} aspectRatio="16/10" />
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
                                  <CommentCountBadge count={(run as any).comment_count} />
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

    {selectedRunsForBulk.length > 0 && (
      <div className="fixed bottom-6 left-1/2 transform -translate-x-1/2 flex flex-col items-center gap-2 z-50">
        {bulkError && (
          <div className="flex items-center gap-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 text-red-700 dark:text-red-400 rounded-lg px-4 py-2 text-xs shadow-lg max-w-md">
            <span className="flex-1">{bulkError}</span>
            <button onClick={() => setBulkError(null)} aria-label="Dismiss error" className="opacity-60 hover:opacity-100">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
        <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 shadow-2xl rounded-lg px-6 py-4 flex items-center gap-6">
          <span className="text-xs font-semibold text-slate-500 dark:text-slate-400">
            {selectedRunsForBulk.length} runs selected
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPendingBulkDecision('approved')}
              disabled={!can('approve')}
              className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-xs font-bold uppercase tracking-wider transition-colors"
            >
              Approve
            </button>
            <button
              onClick={() => setPendingBulkDecision('rejected')}
              disabled={!can('approve')}
              className="px-4 py-2 bg-red-600 hover:bg-red-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-xs font-bold uppercase tracking-wider transition-colors"
            >
              Reject
            </button>
            <button
              onClick={() => setSelectedRunsForBulk([])}
              className="px-3 py-2 bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      </div>
    )}

    {pendingBulkDecision && (
      <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 px-4" onClick={() => setPendingBulkDecision(null)}>
        <div
          className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-2xl max-w-sm w-full p-6 space-y-4"
          onClick={(e) => e.stopPropagation()}
          role="alertdialog"
          aria-modal="true"
          aria-label={`Confirm ${pendingBulkDecision === 'approved' ? 'approve' : 'reject'} selected runs`}
        >
          <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100">
            {pendingBulkDecision === 'approved' ? 'Approve' : 'Reject'} {selectedRunsForBulk.length} selected run{selectedRunsForBulk.length === 1 ? '' : 's'}?
          </h3>
          <p className="text-xs text-slate-500 dark:text-slate-400">This will update the review status for every selected run. This action can be redone individually afterwards, but not bulk-undone.</p>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setPendingBulkDecision(null)}
              className="px-3 py-2 bg-slate-200 dark:bg-slate-800 hover:bg-slate-300 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded text-xs font-semibold transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={confirmBulkReview}
              className={cn(
                "px-4 py-2 rounded text-xs font-bold uppercase tracking-wider text-white transition-colors",
                pendingBulkDecision === 'approved' ? "bg-green-600 hover:bg-green-700" : "bg-red-600 hover:bg-red-700"
              )}
            >
              Confirm {pendingBulkDecision === 'approved' ? 'Approve' : 'Reject'}
            </button>
          </div>
        </div>
      </div>
    )}

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
                  src={`/artifacts/${selectedRun.id}/${previewTab === 'diff' ? 'diff_overlay' : previewTab}.webp`}
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

function FilterSelect({ label, options, value, onChange }: { label: string, options: string[], value: string, onChange: (val: string) => void }) {
  return (
    <div className="flex gap-2 items-center px-3 py-1.5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-lg shadow-sm min-w-0">
      <span className="text-[10px] font-bold uppercase tracking-widest text-slate-400 shrink-0">{label}:</span>
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="border-none bg-transparent focus:ring-0 text-primary cursor-pointer p-0 pr-6 text-xs font-bold outline-none min-w-0 max-w-[45vw] sm:max-w-[160px] truncate"
      >
        {options.map(opt => <option key={opt} value={opt}>{opt}</option>)}
      </select>
    </div>
  );
}

