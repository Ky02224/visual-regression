import { PageHeader } from '../components/ui/PageHeader';
import React from 'react';
import { 
  Search, 
  Maximize2, 
  RotateCcw, 
  Trash2, 
  Calendar,
  Smartphone,
  Monitor,
  Globe,
  CheckCircle2,
  Plus,
  X,
  GitBranch,
  Link,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { Baseline } from '../types';
import { useRole } from '../context/RoleContext';
import { useDebounce } from '../hooks/useDebounce';

function parseBaselineUrl(urlStr: string): { host: string; path: string } {
  if (!urlStr) return { host: 'Custom', path: '—' };
  try {
    const u = new URL(urlStr.startsWith('http') ? urlStr : `https://${urlStr}`);
    return { host: u.hostname, path: u.pathname || '/' };
  } catch {
    return { host: 'Custom', path: urlStr };
  }
}

export function Baselines() {
  const { role, userName, userEmail } = useRole();
  const [baselines, setBaselines] = React.useState<Baseline[]>([]);
  const [selectedBaseline, setSelectedBaseline] = React.useState<Baseline | null>(null);
  const [viewMode, setViewMode] = React.useState<'grid' | 'list'>('grid');
  const [isModalOpen, setIsModalOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState('');
  const debouncedSearchQuery = useDebounce(searchQuery, 150);
  const [loading, setLoading] = React.useState(true);
  const [restoreHint, setRestoreHint] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<string | null>(null);
  const [selectedVersion, setSelectedVersion] = React.useState<string | null>(null);
  const [modalError, setModalError] = React.useState<string | null>(null);
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [baselineDetails, setBaselineDetails] = React.useState<any>(null);
  const [browserFilter, setBrowserFilter] = React.useState('All');
  const [sourceFilter, setSourceFilter] = React.useState<'All' | 'Single' | 'Crawl'>('All');
  const [selectedHost, setSelectedHost] = React.useState<string>('All');
  const [thresholdSaved, setThresholdSaved] = React.useState(false);
  const [currentPage, setCurrentPage] = React.useState(1);
  const PAGE_SIZE = 24;



  const [newBaseline, setNewBaseline] = React.useState({
    name: '',
    url: '',
    browser: 'chromium' as 'chromium' | 'firefox' | 'webkit',
    device: 'desktop' as 'desktop' | 'iPhone 13' | 'Pixel 5' | 'iPad (gen 7)',
    viewport: '1440x900',
    locale: '',
    timezone_id: '',
    color_scheme: 'light' as 'light' | 'dark' | 'no-preference',
    wait_ms: 1200,
  });

  const fetchBaselines = React.useCallback(() => {
    setLoading(true);
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        const mapped = (data.baselines || []).map((b: any) => {
          const { host, path } = parseBaselineUrl(b.url || '');
          const capture = b.capture || {};
          return {
            id: b.name,
            // Display clean URL path as label, fall back to baseline name
            label: b.url ? path : b.name,
            url: b.url || '',
            browser: b.browser || 'Unknown',
            device: b.device || 'Desktop',
            locale: b.locale || '',
            updatedAt: b.updated_at || b.created_at || 'Unknown',
            // Show version count instead of empty string
            version: String(b.version_count || 0),
            imageUrl: b.current_image_href || `/baseline/${b.name}/baseline.webp`,
            source: capture.source || b.source || 'website-capture',
            host,
            versionCount: b.version_count || 0,
            startUrl: capture.start_url || null,
          };
        });
        setBaselines(mapped);
        setSelectedBaseline(prev => {
          if (prev) {
            // Re-sync to the freshly fetched copy of the same baseline (keeps
            // version count / thumbnail current) instead of silently jumping
            // to mapped[0] on every refetch, or holding a stale object.
            return mapped.find((m: any) => m.id === prev.id) || prev;
          }
          return mapped.length > 0 ? mapped[0] : null;
        });
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
        setActionError('Failed to load baselines — please try again.');
      });
  }, []);


  React.useEffect(() => {
    fetchBaselines();
  }, [fetchBaselines]);

  React.useEffect(() => {
    setSelectedVersion(null);
    if (selectedBaseline) {
      fetch(`/api/baseline?id=${selectedBaseline.id}`)
        .then(res => { if (!res.ok) throw new Error('Failed'); return res.json(); })
        .then(data => setBaselineDetails(data))
        .catch(() => setBaselineDetails(null));
    } else {
      setBaselineDetails(null);
    }
  }, [selectedBaseline]);

  const handleDelete = async (name: string) => {
    setDeleteTarget(null);
    setIsExecuting(true);
    setActionError(null);
    try {
      const res = await fetch('/api/baseline/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name })
      });
      const data = await res.json();
      if (data.ok) {
        setSelectedBaseline(null);
        fetchBaselines();
      } else {
        setActionError(data.error || 'Failed to delete baseline');
      }
    } catch {
      setActionError('Network failure — please try again.');
    } finally {
      setIsExecuting(false);
    }
  };

  const handleRestore = async (name: string, version: string) => {
    setIsExecuting(true);
    try {
      const res = await fetch('/api/baseline/restore', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ name, version, restored_by: userName || userEmail || role })
      });
      const data = await res.json();
      if (data.ok) {
        setActionError(null);
        setSelectedVersion(null);
        fetchBaselines();
      } else {
        setActionError(data.error || 'Failed to restore baseline');
      }
    } catch {
      setActionError('Network failure — please try again.');
    } finally {
      setIsExecuting(false);
    }
  };

  const openCreateModal = () => {
    setNewBaseline({
      name: '',
      url: '',
      browser: 'chromium',
      device: 'desktop',
      viewport: '1440x900',
      locale: '',
      timezone_id: '',
      color_scheme: 'light',
      wait_ms: 1200,
    });
    setIsModalOpen(true);
  };

  const submitCreateBaseline = async () => {
    setModalError(null);
    if (!newBaseline.name.trim()) {
      setModalError('Baseline name is required.');
      return;
    }
    if (!newBaseline.url.trim()) {
      setModalError('Target URL is required.');
      return;
    }

    setIsExecuting(true);
    try {
      const payload: Record<string, unknown> = {
        name: newBaseline.name.trim(),
        url: newBaseline.url.trim(),
        browser: newBaseline.browser,
        viewport: newBaseline.viewport,
        wait_ms: newBaseline.wait_ms,
        color_scheme: newBaseline.color_scheme,
        updated_by: role,
      };
      if (newBaseline.device !== 'desktop') payload.device = newBaseline.device;
      if (newBaseline.locale.trim()) payload.locale = newBaseline.locale.trim();
      if (newBaseline.timezone_id.trim()) payload.timezone_id = newBaseline.timezone_id.trim();

      const res = await fetch('/api/actions/create-baseline', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.stderr || data.error || 'Failed to create baseline');
      }
      setIsModalOpen(false);
      setSelectedBaseline(null);
      fetchBaselines();
    } catch (err) {
      setModalError(err instanceof Error ? err.message : 'Failed to create baseline');
    } finally {
      setIsExecuting(false);
    }
  };

  // Derived: all unique hosts for sidebar
  const allHosts = React.useMemo(() => {
    const hosts = new Set(baselines.map(b => b.host));
    return ['All', ...Array.from(hosts).sort()];
  }, [baselines]);

  // Host badge counts
  const hostCounts = React.useMemo(() => {
    const counts: Record<string, number> = {};
    baselines.forEach(b => { counts[b.host] = (counts[b.host] || 0) + 1; });
    return counts;
  }, [baselines]);

  const filteredBaselines = React.useMemo(() => {
    const q = debouncedSearchQuery.toLowerCase();
    return baselines.filter(baseline => {
      const matchesSearch = !q ||
        (baseline.label || '').toLowerCase().includes(q) ||
        (baseline.url || '').toLowerCase().includes(q) ||
        (baseline.id || '').toLowerCase().includes(q);
      const matchesBrowser = browserFilter === 'All' || (baseline.browser || '').toLowerCase().includes(browserFilter.toLowerCase());
      const matchesSource =
        sourceFilter === 'All' ||
        (sourceFilter === 'Single' && (baseline.source === 'website-capture' || baseline.source === 'local-image')) ||
        (sourceFilter === 'Crawl' && baseline.source === 'auto-crawl');
      const matchesHost = selectedHost === 'All' || baseline.host === selectedHost;
      return matchesSearch && matchesBrowser && matchesSource && matchesHost;
    });
  }, [baselines, debouncedSearchQuery, browserFilter, sourceFilter, selectedHost]);

  const totalPages = Math.ceil(filteredBaselines.length / PAGE_SIZE);
  const paginatedBaselines = filteredBaselines.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);

  // Reset to page 1 when filters change
  React.useEffect(() => { setCurrentPage(1); }, [debouncedSearchQuery, browserFilter, sourceFilter, selectedHost]);


  if (loading) {
    return (
      <div className="p-8 min-h-screen">
        <div className="max-w-7xl mx-auto space-y-12">
          {/* Header skeleton */}
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 border-b border-[var(--outline)] pb-8">
            <div className="flex-1 space-y-3">
              <div className="h-9 w-48 rounded-md animate-shimmer" />
              <div className="h-5 w-72 rounded-md animate-shimmer" />
              <div className="mt-8 h-12 max-w-md rounded-md animate-shimmer" />
            </div>
            <div className="h-10 w-40 rounded-xl animate-shimmer" />
          </div>
          {/* Grid skeleton */}
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-12">
            <div className="xl:col-span-8">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="rounded-xl border border-[var(--outline)] overflow-hidden">
                    <div className="aspect-video animate-shimmer" />
                    <div className="p-4 space-y-2">
                      <div className="h-4 w-3/4 rounded animate-shimmer" />
                      <div className="h-3 w-1/2 rounded animate-shimmer" />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="xl:col-span-4">
              <div className="h-[500px] rounded-md border border-[var(--outline)] animate-shimmer" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="p-8 min-h-screen">
      <div className="max-w-7xl mx-auto space-y-8">
        {/* Header & Filters */}
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-8 border-b border-[var(--outline)] pb-8">
          <div className="flex-1">
            <h2 className="text-3xl font-bold text-[var(--on-surface)] mb-2">Baseline Library</h2>
            <p className="text-[var(--on-surface-variant)] font-medium">Manage and audit visual ground truths across your application.</p>
            
            {/* Search Bar */}
            <div className="mt-8 relative max-w-md group">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-300 group-focus-within:text-accent transition-colors" />
              <input 
                type="text"
                placeholder="Search by label, URL or slug..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[var(--surface)] border border-[var(--outline)] rounded-md py-3.5 pl-12 pr-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all shadow-sm dark:text-slate-100"
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {/* View Mode */}
            <div className="flex items-center bg-[var(--surface)] border border-[var(--outline)] rounded-xl p-1 shadow-sm">
              <button 
                onClick={() => setViewMode('grid')}
                aria-pressed={viewMode === 'grid'}
                className={cn(
                  "px-5 py-2 rounded-lg text-[10px] font-bold transition-all",
                  viewMode === 'grid' ? "bg-primary text-white shadow-md" : "text-[var(--on-surface-variant)] hover:text-primary"
                )}
              >
                Grid
              </button>
              <button 
                onClick={() => setViewMode('list')}
                aria-pressed={viewMode === 'list'}
                className={cn(
                  "px-5 py-2 rounded-lg text-[10px] font-bold transition-all",
                  viewMode === 'list' ? "bg-primary text-white shadow-md" : "text-[var(--on-surface-variant)] hover:text-primary"
                )}
              >
                List
              </button>
            </div>
            {/* Browser Filter */}
            <select
              value={browserFilter}
              onChange={e => setBrowserFilter(e.target.value)}
              className="bg-[var(--surface)] border border-[var(--outline)] rounded-xl px-4 py-2 text-[10px] font-bold text-primary dark:text-slate-300 focus:ring-0 cursor-pointer outline-none shadow-sm"
            >
              <option value="All" className="dark:bg-slate-900">All Browsers</option>
              <option value="chromium" className="dark:bg-slate-900">Chromium</option>
              <option value="firefox" className="dark:bg-slate-900">Firefox</option>
              <option value="webkit" className="dark:bg-slate-900">WebKit</option>
            </select>
            {/* Source Filter */}
            <select
              value={sourceFilter}
              onChange={e => setSourceFilter(e.target.value as any)}
              className="bg-[var(--surface)] border border-[var(--outline)] rounded-xl px-4 py-2 text-[10px] font-bold text-primary dark:text-slate-300 focus:ring-0 cursor-pointer outline-none shadow-sm"
            >
              <option value="All" className="dark:bg-slate-900">All Sources</option>
              <option value="Single" className="dark:bg-slate-900">Single Capture</option>
              <option value="Crawl" className="dark:bg-slate-900">Auto-Crawled</option>
            </select>
          </div>
        </div>

        {/* Main 3-column Layout: Website Sidebar + Grid + Detail Panel */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-6">

          {/* Website Sidebar */}
          <div className="xl:col-span-2">
            <div className="sticky top-8 max-h-[calc(100vh-4rem)] overflow-y-auto pr-2 custom-scrollbar">
              <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-widest mb-3 px-1">Websites</h4>
              <div className="space-y-1">
                {allHosts.map(host => (
                  <button
                    key={host}
                    onClick={() => setSelectedHost(host)}
                    className={cn(
                      "w-full text-left px-3 py-2 rounded-lg text-xs font-medium transition-all flex items-center justify-between gap-2",
                      selectedHost === host
                        ? "bg-primary text-white shadow-sm"
                        : "text-[var(--on-surface-variant)] hover:bg-slate-100 dark:hover:bg-slate-800"
                    )}
                  >
                    <span className="truncate">{host === 'All' ? 'All Websites' : host}</span>
                    <span className={cn(
                      "text-[9px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0",
                      selectedHost === host ? "bg-white/20 text-white" : "bg-slate-100 dark:bg-slate-800 text-[var(--on-surface-variant)]"
                    )}>
                      {host === 'All' ? baselines.length : (hostCounts[host] || 0)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Centre: Baseline Grid/List */}
          <div className="xl:col-span-6 space-y-6">
            {paginatedBaselines.length > 0 && (
              <BaselineGroup
                title={selectedHost === 'All' ? 'All Baselines' : selectedHost}
                count={filteredBaselines.length}
                showing={paginatedBaselines.length}
              >
                <div className={viewMode === 'grid' ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-1 border border-[var(--outline)] rounded-md overflow-hidden"}>
                  {paginatedBaselines.map(baseline => (
                    <BaselineCard 
                      key={baseline.id} 
                      baseline={baseline} 
                      isSelected={selectedBaseline?.id === baseline.id}
                      onClick={() => setSelectedBaseline(baseline)}
                      viewMode={viewMode}
                    />
                  ))}
                </div>
              </BaselineGroup>
            )}

            {filteredBaselines.length === 0 && (
              <div className="flex flex-col items-center justify-center py-32 text-slate-300 dark:text-slate-700">
                <Search className="w-16 h-16 mb-6 opacity-20" />
                <p className="text-xl font-bold text-[var(--on-surface)]">No baselines found</p>
                <p className="text-sm mt-2">Try adjusting your search or filter parameters.</p>
                <button 
                  onClick={() => { setSearchQuery(''); setBrowserFilter('All'); setSourceFilter('All'); setSelectedHost('All'); }}
                  className="mt-6 px-6 py-2 bg-slate-100 text-primary text-xs font-bold rounded-lg hover:bg-slate-200 transition-all"
                >
                  Clear all filters
                </button>
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-between pt-4 border-t border-[var(--outline)]">
                <p className="text-xs text-[var(--on-surface-variant)]">
                  Showing {(currentPage - 1) * PAGE_SIZE + 1}–{Math.min(currentPage * PAGE_SIZE, filteredBaselines.length)} of {filteredBaselines.length}
                </p>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    className="w-8 h-8 flex items-center justify-center rounded-lg border border-[var(--outline)] text-[var(--on-surface-variant)] hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    const pg = currentPage <= 3 ? i + 1 : currentPage - 2 + i;
                    if (pg < 1 || pg > totalPages) return null;
                    return (
                      <button
                        key={pg}
                        onClick={() => setCurrentPage(pg)}
                        className={cn(
                          "w-8 h-8 flex items-center justify-center rounded-lg text-xs font-bold transition-all",
                          currentPage === pg ? "bg-primary text-white shadow-sm" : "border border-[var(--outline)] text-[var(--on-surface-variant)] hover:bg-slate-50 dark:hover:bg-slate-800"
                        )}
                      >
                        {pg}
                      </button>
                    );
                  })}
                  <button
                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                    className="w-8 h-8 flex items-center justify-center rounded-lg border border-[var(--outline)] text-[var(--on-surface-variant)] hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-all"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </div>


          {/* Right Column: Detail View */}
          <div className="xl:col-span-4">
            <div className="sticky top-8 max-h-[calc(100vh-4rem)] overflow-y-auto pr-2 custom-scrollbar">
              <AnimatePresence mode="wait">
                {selectedBaseline ? (
                  <motion.div 
                    key={selectedBaseline.id}
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.95 }}
                    className="bg-[var(--surface)] border border-[var(--outline)] rounded-md overflow-hidden shadow-sm"
                  >
                    {/* Detail Header */}
                    <div className="p-6 border-b border-slate-100 dark:border-slate-800 flex items-center justify-between">
                      <div>
                        <h3 className="text-xl font-bold text-[var(--on-surface)] leading-tight">{selectedBaseline.label}</h3>
                        <p className="text-[10px] font-bold text-[var(--on-surface-variant)] font-medium mt-1">Version {selectedBaseline.version}</p>
                      </div>
                      <button 
                        onClick={() => setSelectedBaseline(null)}
                        className="w-10 h-10 rounded-full hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-center text-slate-300 transition-colors"
                      >
                        <X className="w-4 h-4" />
                      </button>
                    </div>

                    {/* Crawl Source Info for auto-crawled baselines */}
                    {selectedBaseline.source === 'auto-crawl' && (
                      <div className="px-6 pt-2">
                        <div className="flex items-center gap-2 p-3 bg-purple-50 dark:bg-purple-900/20 rounded-lg border border-purple-100 dark:border-purple-800">
                          <GitBranch className="w-3.5 h-3.5 text-purple-500 flex-shrink-0" />
                          <div className="min-w-0">
                            <p className="text-[9px] font-bold text-purple-600 dark:text-purple-400 uppercase tracking-wider">Auto-Crawled</p>
                            {selectedBaseline.startUrl && (
                              <p className="text-[10px] text-purple-700 dark:text-purple-300 truncate mt-0.5">
                                From: {selectedBaseline.startUrl}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Large Preview */}
                    {(() => {
                      const selectedVersionDetails = selectedVersion && baselineDetails?.versions?.find((v: any) => v.version === selectedVersion);
                      const previewSrc = selectedVersionDetails ? selectedVersionDetails.image_href : selectedBaseline.imageUrl;
                      return (
                        <div className="p-6">
                          <div className="rounded-md overflow-hidden border border-slate-100 dark:border-slate-800 bg-stone-50 dark:bg-zinc-900 relative aspect-[4/3] group cursor-zoom-in">
                            {selectedVersionDetails && (
                              <div className="absolute top-3 left-3 bg-amber-500 text-white px-2.5 py-1.5 rounded-md text-[10px] font-bold shadow-md z-10 animate-pulse">
                                Viewing Archive: {selectedVersion}
                              </div>
                            )}
                            <img 
                              src={previewSrc} 
                              alt="Full Preview" 
                              className="w-full h-full object-cover object-top transition-transform duration-700 group-hover:scale-110"
                              referrerPolicy="no-referrer"
                            />
                            <div className="absolute inset-0 bg-primary/0 group-hover:bg-primary/5 transition-colors" />
                          </div>
                        </div>
                      );
                    })()}

                    {/* Meta Info */}
                    <div className="px-6 pb-6 space-y-6">
                      <div className="grid grid-cols-2 gap-4 p-4 bg-stone-50 dark:bg-zinc-900 rounded-md border border-slate-100 dark:border-slate-800">
                        <InfoItem label="Browser" value={selectedBaseline.browser} />
                        <InfoItem label="Device" value={selectedBaseline.device} />
                        <InfoItem label="Locale" value={selectedBaseline.locale || '—'} />
                        <InfoItem label="Versions" value={selectedBaseline.versionCount > 0 ? `${selectedBaseline.versionCount} archived` : 'No history'} />
                      </div>

                      <div className="p-4 bg-stone-50 dark:bg-zinc-900 rounded-md border border-slate-100 dark:border-slate-800 space-y-3">
                        <div className="flex items-center justify-between">
                          <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-widest">Mismatch Threshold</h4>
                          <span className="text-[10px] font-semibold text-slate-400">Default: 0.5%</span>
                        </div>
                        <div className="flex gap-2 items-center">
                          <input 
                            type="number"
                            step="0.01"
                            min="0"
                            max="100"
                            placeholder="0.5"
                            value={baselineDetails?.custom_threshold_pct ?? ''}
                            onChange={(e) => {
                              const val = e.target.value === '' ? null : parseFloat(e.target.value);
                              setBaselineDetails((prev: any) => ({ ...prev, custom_threshold_pct: val }));
                            }}
                            className="bg-white dark:bg-zinc-800 border border-slate-200 dark:border-slate-700 rounded px-2.5 py-1 text-xs outline-none focus:ring-2 focus:ring-primary/10 w-24 dark:text-slate-100"
                          />
                          <span className="text-xs text-[var(--on-surface-variant)]">%</span>
                          <button
                            onClick={async () => {
                              setIsExecuting(true);
                              try {
                                const res = await fetch('/api/baseline/update-threshold', {
                                  method: 'POST',
                                  headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ name: selectedBaseline.id, threshold_pct: baselineDetails?.custom_threshold_pct })
                                });
                                const result = await res.json();
                                if (res.ok && result.ok) {
                                  setThresholdSaved(true);
                                  setTimeout(() => setThresholdSaved(false), 2000);
                                } else {
                                  setActionError(result.error || 'Failed to save threshold');
                                }
                              } catch (_) {
                                setActionError('Network failure — please try again.');
                              }
                              setIsExecuting(false);
                            }}
                            disabled={isExecuting}
                            className="px-3 py-1 rounded bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-[11px] font-bold transition-all ml-auto"
                          >
                            Save
                          </button>
                        </div>
                        {thresholdSaved && (
                          <p className="text-[10px] text-emerald-600 dark:text-emerald-450 font-semibold text-right">Saved!</p>
                        )}
                      </div>

                      {(baselineDetails?.ignore_regions?.length ?? 0) > 0 && (
                        <div className="p-4 bg-stone-50 dark:bg-zinc-900 rounded-md border border-slate-100 dark:border-slate-800 space-y-2">
                          <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-widest">Ignore regions</h4>
                          <ul className="space-y-1 max-h-28 overflow-y-auto">
                            {baselineDetails.ignore_regions.map((rect: number[], idx: number) => (
                              <li key={idx} className="text-xs font-mono text-[var(--on-surface-variant)]">
                                [{rect[0]}, {rect[1]}] · {rect[2]}×{rect[3]}px
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {/* Versions Timeline */}
                      {baselineDetails?.versions && baselineDetails.versions.length > 0 && (
                        <div className="space-y-4">
                          <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] font-medium px-1">Version History</h4>
                          <div className="space-y-2 max-h-[240px] overflow-y-auto pr-2 custom-scrollbar">
                            <HistoryItem 
                              active 
                              label="Current Version" 
                              date={selectedBaseline.updatedAt}
                            />
                            {baselineDetails.versions.map((v: any) => (
                              <button
                                key={v.version}
                                role="button"
                                tabIndex={0}
                                onClick={() => setSelectedVersion(selectedVersion === v.version ? null : v.version)}
                                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedVersion(selectedVersion === v.version ? null : v.version); } }}
                                className="w-full text-left"
                              >
                                <HistoryItem 
                                  label={`Archive: ${v.version}`}
                                  date={v.archived_at || "Archived Item"}
                                  selected={selectedVersion === v.version}
                                />
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="grid grid-cols-1 gap-3 pt-4">
                        <button
                          onClick={() => {
                            if (selectedVersion) {
                              handleRestore(selectedBaseline.id, selectedVersion);
                            } else {
                              setRestoreHint(true);
                              setTimeout(() => setRestoreHint(false), 3000);
                            }
                          }}
                          disabled={role === 'viewer' || isExecuting}
                          className={cn(
                            "flex items-center justify-center gap-2 py-4 rounded-xl font-bold text-sm transition-all disabled:opacity-30 disabled:cursor-not-allowed",
                            selectedVersion
                              ? "bg-primary text-white shadow-lg shadow-primary/20 hover:bg-slate-800"
                              : "border border-[var(--outline)] text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
                          )}
                        >
                          <RotateCcw className={cn("w-3.5 h-3.5", isExecuting && "animate-spin")} /> 
                          {selectedVersion ? `Restore Version: ${selectedVersion}` : 'Restore'}
                        </button>
                        {restoreHint && (
                          <p className="text-[11px] text-amber-600 dark:text-amber-400 text-center font-medium px-1">
                            Select an archived version above to restore.
                          </p>
                        )}
                        {deleteTarget === selectedBaseline.id ? (
                          <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-3 space-y-2">
                            <p className="text-xs font-bold text-red-700 dark:text-red-400 text-center">Delete "{selectedBaseline.label}"?</p>
                            <div className="flex gap-2">
                              <button onClick={() => setDeleteTarget(null)} className="flex-1 py-2 rounded-lg border border-[var(--outline)] text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-stone-100 dark:hover:bg-zinc-800 transition-all">Cancel</button>
                              <button onClick={() => handleDelete(selectedBaseline.id)} disabled={isExecuting} className="flex-1 py-2 rounded-lg bg-red-600 text-white text-xs font-bold hover:bg-red-700 transition-all disabled:opacity-50">
                                {isExecuting ? 'Deleting...' : 'Confirm'}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            onClick={() => setDeleteTarget(selectedBaseline.id)}
                            disabled={role === 'viewer' || isExecuting}
                            className="flex items-center justify-center gap-2 py-4 rounded-xl bg-red-50 dark:bg-red-900/10 text-red-600 dark:text-red-400 font-bold text-xs hover:bg-red-100 dark:hover:bg-red-900/20 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                            <Trash2 className="w-3.5 h-3.5" /> Delete
                          </button>
                        )}
                        {actionError && (
                          <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-900/20 dark:border-red-800 px-3 py-2 text-xs font-medium text-red-700 dark:text-red-400 flex items-center justify-between gap-2">
                            <span>{actionError}</span>
                            <button onClick={() => setActionError(null)} className="text-red-400 hover:text-red-600 flex-shrink-0">✕</button>
                          </div>
                        )}
                      </div>
                    </div>
                  </motion.div>
                ) : (
                  <div className="h-[500px] rounded-md border-2 border-dashed border-[var(--outline)] flex flex-col items-center justify-center p-12 text-center">
                    <div className="w-16 h-16 rounded-full bg-slate-50 dark:bg-slate-900 flex items-center justify-center text-slate-300 mb-6">
                      <Maximize2 className="w-8 h-8" />
                    </div>
                    <h4 className="text-lg font-bold text-[var(--on-surface)] mb-2">No Baseline Selected</h4>
                    <p className="text-sm text-[var(--on-surface-variant)] max-w-xs">Select a baseline from the library to view its details and version history.</p>
                  </div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </div>
      </div>

      {/* FAB */}
      {role !== 'viewer' && (
        <button 
          onClick={openCreateModal}
          aria-label="Create new baseline"
          className="fixed bottom-8 right-8 w-14 h-14 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white shadow-2xl flex items-center justify-center hover:scale-110 active:scale-95 transition-all z-30"
        >
          <Plus className="w-6 h-6" />
        </button>
      )}

      {/* New Baseline Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            onClick={() => setIsModalOpen(false)}
            className="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
          />
          <motion.div 
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            className="relative w-full max-w-xl bg-[var(--surface)] rounded-md shadow-2xl overflow-hidden"
          >
            <div className="p-8 border-b border-slate-100 dark:border-slate-800 flex justify-between items-center">
              <h3 className="text-2xl font-bold text-[var(--on-surface)]">New Baseline</h3>
              <button onClick={() => setIsModalOpen(false)} className="w-10 h-10 rounded-full hover:bg-slate-100 flex items-center justify-center text-on-surface-variant">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="p-8 space-y-6">
              <div className="space-y-2">
                <label className="text-xs font-bold font-medium text-on-surface-variant">Baseline Name</label>
                <input
                  value={newBaseline.name}
                  onChange={(e) => setNewBaseline(prev => ({ ...prev, name: e.target.value }))}
                  className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                  placeholder="e.g. landing-home-chromium-desktop"
                />
              </div>
              <div className="space-y-2">
                <label className="text-xs font-bold font-medium text-on-surface-variant">Target URL</label>
                <input
                  value={newBaseline.url}
                  onChange={(e) => setNewBaseline(prev => ({ ...prev, url: e.target.value }))}
                  className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                  placeholder="https://app.example.com/dashboard"
                />
              </div>
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold font-medium text-on-surface-variant">Browser</label>
                  <select
                    value={newBaseline.browser}
                    onChange={(e) => setNewBaseline(prev => ({ ...prev, browser: e.target.value as any }))}
                    className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                  >
                    <option value="chromium" className="dark:bg-slate-900">Chromium (Chrome)</option>
                    <option value="firefox" className="dark:bg-slate-900">Firefox</option>
                    <option value="webkit" className="dark:bg-slate-900">WebKit (Safari)</option>
                  </select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold font-medium text-on-surface-variant">Device</label>
                  <select
                    value={newBaseline.device}
                    onChange={(e) => setNewBaseline(prev => ({ ...prev, device: e.target.value as any }))}
                    className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                  >
                    <option value="desktop" className="dark:bg-slate-900">Desktop</option>
                    <option value="iPhone 13" className="dark:bg-slate-900">iPhone 13</option>
                    <option value="Pixel 5" className="dark:bg-slate-900">Pixel 5</option>
                    <option value="iPad (gen 7)" className="dark:bg-slate-900">iPad (gen 7)</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold font-medium text-on-surface-variant">Viewport</label>
                  <input
                    value={newBaseline.viewport}
                    onChange={(e) => setNewBaseline(prev => ({ ...prev, viewport: e.target.value }))}
                    className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                    placeholder="1440x900"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold font-medium text-on-surface-variant">Locale (optional)</label>
                  <input
                    value={newBaseline.locale}
                    onChange={(e) => setNewBaseline(prev => ({ ...prev, locale: e.target.value.replace('_', '-') }))}
                    className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                    placeholder="en-US"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-6">
                <div className="space-y-2">
                  <label className="text-xs font-bold font-medium text-on-surface-variant">Timezone (optional)</label>
                  <input
                    value={newBaseline.timezone_id}
                    onChange={(e) => setNewBaseline(prev => ({ ...prev, timezone_id: e.target.value }))}
                    className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                    placeholder="Asia/Kuala_Lumpur"
                  />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-bold font-medium text-on-surface-variant">Color scheme</label>
                  <select
                    value={newBaseline.color_scheme}
                    onChange={(e) => setNewBaseline(prev => ({ ...prev, color_scheme: e.target.value as any }))}
                    className="w-full bg-stone-50 dark:bg-zinc-900 border border-slate-100 dark:border-slate-800 rounded-xl py-3 px-4 text-sm outline-none focus:ring-2 focus:ring-primary/10 dark:text-slate-100"
                  >
                    <option value="light" className="dark:bg-slate-900">Light</option>
                    <option value="dark" className="dark:bg-slate-900">Dark</option>
                    <option value="no-preference" className="dark:bg-slate-900">No preference</option>
                  </select>
                </div>
              </div>
              <div className="p-4 bg-primary-container/20 rounded-xl border border-primary/10">
                <p className="text-xs text-primary font-medium leading-relaxed">
                  Initializing a new baseline will capture a high-resolution snapshot of the target URL to serve as the ground truth for future regression tests.
                </p>
              </div>
            </div>
            <div className="px-8 pb-2">
              {modalError && (
                <div className="rounded-lg border border-red-200 bg-red-50 dark:bg-red-900/20 dark:border-red-800 px-3 py-2 text-xs font-medium text-red-700 dark:text-red-400 flex items-center justify-between gap-2">
                  <span>{modalError}</span>
                  <button onClick={() => setModalError(null)} className="text-red-400 hover:text-red-600 flex-shrink-0">✕</button>
                </div>
              )}
            </div>
            <div className="p-8 pt-4 bg-stone-50 dark:bg-zinc-900 flex justify-end gap-4">
              <button onClick={() => setIsModalOpen(false)} className="px-6 py-2.5 text-sm font-bold text-on-surface-variant hover:bg-slate-200 dark:hover:bg-slate-800 rounded-lg transition-all">Cancel</button>
              <button
                onClick={submitCreateBaseline}
                disabled={isExecuting}
                className="px-8 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-bold text-sm shadow-lg shadow-primary/20 hover:scale-105 active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {isExecuting ? 'Capturing...' : 'Capture Baseline'}
              </button>
            </div>
          </motion.div>
        </div>
      )}

    </div>
  );
}

function InfoItem({ label, value }: { label: string, value: string }) {
  return (
    <div>
      <p className="text-[10px] font-bold text-[var(--on-surface-variant)] font-medium mb-1">{label}</p>
      <p className="text-sm font-bold text-primary dark:text-slate-200">{value}</p>
    </div>
  );
}

function BaselineGroup({ title, count, showing, children }: { title: string, count: number, showing?: number, children: React.ReactNode }) {
  return (
    <section>
      <div className="flex items-center gap-3 mb-4">
        <h3 className="text-sm font-bold text-on-surface-variant">{title}</h3>
        <div className="h-px flex-1 bg-outline-variant/15" />
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-surface-container text-primary">
          {showing !== undefined && showing < count ? `${showing} / ${count}` : count} ITEMS
        </span>
      </div>
      {children}
    </section>
  );
}

function BaselineCard({ baseline, isSelected, onClick, viewMode = 'grid' }: { baseline: Baseline, isSelected: boolean, onClick: () => void, viewMode?: 'grid' | 'list', key?: string | number }) {
  const isCrawl = baseline.source === 'auto-crawl';
  if (viewMode === 'list') {
    return (
      <div
        onClick={onClick}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }}
        role="button"
        tabIndex={0}
        aria-pressed={isSelected}
        className={cn(
          "flex items-center gap-4 px-4 py-3 cursor-pointer transition-all border-l-2 hover:bg-slate-50 dark:hover:bg-slate-800/60 focus-visible:outline-none focus-visible:bg-slate-50 dark:focus-visible:bg-slate-800/60",
          isSelected
            ? "border-l-amber-400 bg-amber-50/50 dark:bg-amber-900/10"
            : "border-l-transparent"
        )}
      >
        <div className="w-14 h-10 rounded-lg overflow-hidden bg-slate-100 dark:bg-slate-800 flex-shrink-0 border border-[var(--outline)]">
          <img src={baseline.imageUrl} alt={baseline.label} className="w-full h-full object-cover" referrerPolicy="no-referrer" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h4 className={cn("font-bold text-sm truncate", isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-on-surface dark:text-slate-200")}>{baseline.label}</h4>
            <span className={cn(
              "text-[9px] font-bold px-1.5 py-0.5 rounded-full flex-shrink-0",
              isCrawl ? "bg-purple-100 dark:bg-purple-900/30 text-purple-600 dark:text-purple-400" : "bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400"
            )}>{isCrawl ? 'Crawl' : 'Single'}</span>
          </div>
          <div className="flex items-center gap-3 mt-0.5 text-[11px] text-[var(--on-surface-variant)]">
            <span className="flex items-center gap-1">{baseline.device === 'Mobile' ? <Smartphone className="w-3 h-3" /> : <Monitor className="w-3 h-3" />}{baseline.device}</span>
            <span className="flex items-center gap-1"><Globe className="w-3 h-3" />{baseline.browser}</span>
            <span className="flex items-center gap-1"><Calendar className="w-3 h-3" />{baseline.updatedAt}</span>
          </div>
        </div>
        {baseline.locale && <span className="text-[10px] px-2 py-0.5 rounded font-mono bg-slate-100 dark:bg-slate-800 text-[var(--on-surface-variant)] flex-shrink-0">{baseline.locale}</span>}
        {isSelected && <CheckCircle2 className="w-4 h-4 text-primary flex-shrink-0" />}
      </div>
    );
  }

  return (
    <div
      onClick={onClick}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); } }}
      role="button"
      tabIndex={0}
      aria-pressed={isSelected}
      className={cn(
        "group bg-surface-container-lowest dark:bg-slate-900 rounded-xl border overflow-hidden transition-all cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
        isSelected ? "ring-2 ring-primary/40 border-primary" : "border-outline-variant/5 hover:shadow-md hover:shadow-primary/5"
      )}
    >
      <div className="aspect-video relative overflow-hidden bg-slate-100">
        <img 
          src={baseline.imageUrl} 
          alt={baseline.label} 
          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
          referrerPolicy="no-referrer"
        />
        {/* Source badge overlaid on image top-left */}
        <div className="absolute top-2 left-2">
          <span className={cn(
            "text-[9px] font-bold px-2 py-0.5 rounded-full shadow-sm",
            isCrawl ? "bg-purple-600 text-white" : "bg-indigo-600 text-white"
          )}>{isCrawl ? 'Crawl' : 'Single'}</span>
        </div>
        <div className={cn(
          "absolute inset-0 transition-opacity flex items-center justify-center",
          isSelected ? "bg-primary/10 opacity-100" : "bg-black/40 opacity-0 group-hover:opacity-100"
        )}>
          {isSelected ? (
            <div className="bg-primary text-white p-2 rounded-full shadow-lg">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          ) : (
            <span className="text-white text-xs font-medium flex items-center gap-1">
              <Maximize2 className="w-4 h-4" /> Preview Baseline
            </span>
          )}
        </div>
      </div>
      <div className="p-3">
        <div className="flex justify-between items-start mb-1">
          <h4 className={cn("font-bold text-sm truncate flex-1 mr-2", isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-on-surface dark:text-slate-200")}>{baseline.label}</h4>
        </div>
        {/* Baseline slug as subtitle */}
        {baseline.label !== baseline.id && (
          <p className="text-[9px] text-[var(--on-surface-variant)] font-mono truncate mb-2 opacity-60">{baseline.id}</p>
        )}
        <div className={cn(
          "flex items-center gap-3 text-xs",
          isSelected ? "text-primary/80 dark:text-blue-400/80 font-medium" : "text-on-surface-variant dark:text-[var(--on-surface-variant)]"
        )}>
          <div className="flex items-center gap-1">
            {baseline.device === 'Mobile' ? <Smartphone className="w-3 h-3" /> : <Monitor className="w-3 h-3" />}
            {baseline.device}
          </div>
          <div className="flex items-center gap-1">
            <Globe className="w-3 h-3" />
            {baseline.browser}
          </div>
        </div>
        <p className={cn(
          "text-[10px] mt-2 flex items-center gap-1",
          isSelected ? "text-primary/60" : "text-on-surface-variant/60"
        )}>
          <Calendar className="w-3 h-3" /> Updated {baseline.updatedAt}
        </p>
      </div>
    </div>
  );
}

function HistoryItem({ active, selected, label, date }: { active?: boolean, selected?: boolean, label: string, date: string }) {
  return (
    <div className={cn(
      "flex items-center justify-between p-3 rounded-xl border transition-all cursor-pointer",
      active 
        ? "bg-primary-container/30 border-primary/10" 
        : selected
          ? "bg-amber-50 dark:bg-amber-950/20 border-amber-400 dark:border-amber-700"
          : "hover:bg-surface-container-low border-transparent hover:border-outline-variant/10 group"
    )}>
      <div className="flex items-center gap-3">
        <div className={cn(
          "w-2 h-2 rounded-full", 
          active ? "bg-primary" : selected ? "bg-amber-500" : "bg-outline-variant/40 group-hover:bg-primary/40"
        )} />
        <div>
          <p className="text-xs font-bold text-on-surface">{label}</p>
          <p className="text-[10px] text-on-surface-variant">{date}</p>
        </div>
      </div>
      {active ? (
        <span className="text-[10px] font-mono text-primary font-bold">ACTIVE</span>
      ) : selected ? (
        <span className="text-[10px] font-bold text-amber-600 dark:text-amber-400">SELECTED</span>
      ) : (
        <span className="text-[10px] font-bold text-primary opacity-0 group-hover:opacity-100 transition-opacity">SELECT</span>
      )}
    </div>
  );
}
