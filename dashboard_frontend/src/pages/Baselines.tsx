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
  X
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { Baseline } from '../types';
import { useRole } from '../context/RoleContext';

export function Baselines() {
  const { role } = useRole();
  const [baselines, setBaselines] = React.useState<Baseline[]>([]);
  const [selectedBaseline, setSelectedBaseline] = React.useState<Baseline | null>(null);
  const [viewMode, setViewMode] = React.useState<'grid' | 'list'>('grid');
  const [isModalOpen, setIsModalOpen] = React.useState(false);
  const [searchQuery, setSearchQuery] = React.useState('');
  const [loading, setLoading] = React.useState(true);
  const [restoreHint, setRestoreHint] = React.useState(false);
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = React.useState<string | null>(null);
  const [modalError, setModalError] = React.useState<string | null>(null);
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [baselineDetails, setBaselineDetails] = React.useState<any>(null);
  const [browserFilter, setBrowserFilter] = React.useState('All');

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

  const fetchBaselines = () => {
    setLoading(true);
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        const mapped = (data.baselines || []).map((b: any) => ({
          id: b.name,
          label: b.name,
          url: b.url || b.name,
          browser: b.browser || 'Unknown',
          device: b.device || 'Desktop',
          locale: b.locale || 'Unknown',
          updatedAt: b.updated_at || b.created_at || 'Unknown',
          version: '',
          imageUrl: b.current_image_href || `/baseline/${b.name}/baseline.png`
        }));
        setBaselines(mapped);
        if (mapped.length > 0 && !selectedBaseline) setSelectedBaseline(mapped[0]);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  };

  React.useEffect(() => {
    fetchBaselines();
  }, []);

  React.useEffect(() => {
    if (selectedBaseline) {
      fetch(`/api/baseline?id=${selectedBaseline.id}`)
        .then(res => res.json())
        .then(data => {
          setBaselineDetails(data);
        });
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
        body: JSON.stringify({ name, version, restored_by: role })
      });
      const data = await res.json();
      if (data.ok) {
        setActionError(null);
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
      const payload: any = {
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

  const filteredBaselines = baselines.filter(baseline => {
    const q = searchQuery.toLowerCase();
    const matchesSearch = (baseline.label || '').toLowerCase().includes(q) ||
           (baseline.url || '').toLowerCase().includes(q);
    const matchesBrowser = browserFilter === 'All' || (baseline.browser || '').toLowerCase().includes(browserFilter.toLowerCase());
    return matchesSearch && matchesBrowser;
  });

  return (
    <div className="p-8 min-h-screen">
      <div className="max-w-7xl mx-auto space-y-12">
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
                placeholder="Search by label or URL..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full bg-[var(--surface)] border border-[var(--outline)] rounded-md py-3.5 pl-12 pr-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all shadow-sm dark:text-slate-100"
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center bg-[var(--surface)] border border-[var(--outline)] rounded-xl p-1 shadow-sm">
              <button 
                onClick={() => setViewMode('grid')}
                className={cn(
                  "px-5 py-2 rounded-lg text-[10px] font-bold font-medium transition-all",
                  viewMode === 'grid' ? "bg-primary text-white shadow-md" : "text-[var(--on-surface-variant)] hover:text-primary"
                )}
              >
                Grid
              </button>
              <button 
                onClick={() => setViewMode('list')}
                className={cn(
                  "px-5 py-2 rounded-lg text-[10px] font-bold font-medium transition-all",
                  viewMode === 'list' ? "bg-primary text-white shadow-md" : "text-[var(--on-surface-variant)] hover:text-primary"
                )}
              >
                List
              </button>
            </div>
            <select
              value={browserFilter}
              onChange={e => setBrowserFilter(e.target.value)}
              className="bg-[var(--surface)] border border-[var(--outline)] rounded-xl px-4 py-2 text-[10px] font-bold font-medium text-primary dark:text-slate-300 focus:ring-0 cursor-pointer outline-none shadow-sm"
            >
              <option value="All" className="dark:bg-slate-900">All Browsers</option>
              <option value="chromium" className="dark:bg-slate-900">Chromium</option>
              <option value="firefox" className="dark:bg-slate-900">Firefox</option>
              <option value="webkit" className="dark:bg-slate-900">WebKit</option>
            </select>
          </div>
        </div>

        {/* Content Grid Layout */}
        <div className="grid grid-cols-1 xl:grid-cols-12 gap-12">
          {/* Left Column: Browsing */}
          <div className="xl:col-span-8 space-y-12">
            {filteredBaselines.length > 0 && (
              <BaselineGroup title="All Baselines" count={filteredBaselines.length}>
                <div className={viewMode === 'grid' ? "grid grid-cols-1 md:grid-cols-3 gap-6" : "space-y-1 border border-[var(--outline)] rounded-md overflow-hidden"}>
                  {filteredBaselines.map(baseline => (
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
                <p className="text-sm mt-2">Try adjusting your search parameters.</p>
                <button 
                  onClick={() => setSearchQuery('')}
                  className="mt-6 px-6 py-2 bg-slate-100 text-primary text-xs font-bold font-medium rounded-lg hover:bg-slate-200 transition-all"
                >
                  Clear search
                </button>
              </div>
            )}
          </div>

          {/* Right Column: Detail View */}
          <div className="xl:col-span-4">
            <div className="sticky top-8">
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

                    {/* Large Preview */}
                    <div className="p-6">
                      <div className="rounded-md overflow-hidden border border-slate-100 dark:border-slate-800 bg-stone-50 dark:bg-zinc-900 relative aspect-[4/3] group cursor-zoom-in">
                        <img 
                          src={selectedBaseline.imageUrl} 
                          alt="Full Preview" 
                          className="w-full h-full object-cover object-top transition-transform duration-700 group-hover:scale-110"
                          referrerPolicy="no-referrer"
                        />
                        <div className="absolute inset-0 bg-primary/0 group-hover:bg-primary/5 transition-colors" />
                      </div>
                    </div>

                    {/* Meta Info */}
                    <div className="px-6 pb-6 space-y-6">
                      <div className="grid grid-cols-2 gap-4 p-4 bg-stone-50 dark:bg-zinc-900 rounded-md border border-slate-100 dark:border-slate-800">
                        <InfoItem label="Browser" value={selectedBaseline.browser} />
                        <InfoItem label="Device" value={selectedBaseline.device} />
                        <InfoItem label="Locale" value={selectedBaseline.locale} />
                        <InfoItem label="Current Key" value={selectedBaseline.version} />
                      </div>

                      <div className="p-4 bg-stone-50 dark:bg-zinc-900 rounded-md border border-slate-100 dark:border-slate-800 space-y-2">
                        <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-widest">Ignore regions</h4>
                        {(baselineDetails?.ignore_regions?.length ?? 0) > 0 ? (
                          <ul className="space-y-1 max-h-28 overflow-y-auto">
                            {baselineDetails.ignore_regions.map((rect: number[], idx: number) => (
                              <li key={idx} className="text-xs font-mono text-[var(--on-surface-variant)]">
                                [{rect[0]}, {rect[1]}] · {rect[2]}×{rect[3]}px
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-xs text-[var(--on-surface-variant)] leading-relaxed">
                            None on this baseline. Configure <code className="text-[10px] bg-white dark:bg-zinc-800 px-1 rounded">ignore_regions</code> per case in your suite YAML (Percy-style) to exclude dynamic UI from diffs.
                          </p>
                        )}
                      </div>

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
                              <div key={v.version} onClick={() => handleRestore(selectedBaseline.label, v.version)}>
                                <HistoryItem 
                                  label={`Archive: ${v.version}`}
                                  date={v.archived_at || "Archived Item"}
                                />
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      <div className="grid grid-cols-1 gap-3 pt-4">
                        <button
                          onClick={() => { setRestoreHint(true); setTimeout(() => setRestoreHint(false), 3000); }}
                          disabled={role === 'viewer' || isExecuting}
                          className="flex items-center justify-center gap-2 py-4 rounded-xl border border-[var(--outline)] text-slate-700 dark:text-slate-300 font-bold text-xs hover:bg-slate-50 dark:hover:bg-slate-800 transition-all disabled:opacity-30 disabled:cursor-not-allowed">
                          <RotateCcw className="w-3.5 h-3.5" /> Restore
                        </button>
                        {restoreHint && (
                          <p className="text-[11px] text-amber-600 dark:text-amber-400 text-center font-medium px-1">
                            Select an archived version above to restore.
                          </p>
                        )}
                        {deleteTarget === selectedBaseline.label ? (
                          <div className="rounded-xl border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 p-3 space-y-2">
                            <p className="text-xs font-bold text-red-700 dark:text-red-400 text-center">Delete "{selectedBaseline.label}"?</p>
                            <div className="flex gap-2">
                              <button onClick={() => setDeleteTarget(null)} className="flex-1 py-2 rounded-lg border border-[var(--outline)] text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-stone-100 dark:hover:bg-zinc-800 transition-all">Cancel</button>
                              <button onClick={() => handleDelete(selectedBaseline.label)} disabled={isExecuting} className="flex-1 py-2 rounded-lg bg-red-600 text-white text-xs font-bold hover:bg-red-700 transition-all disabled:opacity-50">
                                {isExecuting ? 'Deleting...' : 'Confirm'}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <button
                            onClick={() => setDeleteTarget(selectedBaseline.label)}
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
                    onChange={(e) => setNewBaseline(prev => ({ ...prev, locale: e.target.value }))}
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

function BaselineGroup({ title, count, children }: { title: string, count: number, children: React.ReactNode }) {
  return (
    <section>
      <div className="flex items-center gap-3 mb-6">
        <h3 className="text-sm font-bold font-medium text-on-surface-variant">{title}</h3>
        <div className="h-px flex-1 bg-outline-variant/15" />
        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-surface-container text-primary">{count} ITEMS</span>
      </div>
      {children}
    </section>
  );
}

function BaselineCard({ baseline, isSelected, onClick, viewMode = 'grid' }: { baseline: Baseline, isSelected: boolean, onClick: () => void, viewMode?: 'grid' | 'list', key?: string | number }) {
  if (viewMode === 'list') {
    return (
      <div
        onClick={onClick}
        className={cn(
          "flex items-center gap-4 px-4 py-3 cursor-pointer transition-all border-l-2 hover:bg-slate-50 dark:hover:bg-slate-800/60",
          isSelected
            ? "border-l-amber-400 bg-amber-50/50 dark:bg-amber-900/10"
            : "border-l-transparent"
        )}
      >
        <div className="w-14 h-10 rounded-lg overflow-hidden bg-slate-100 dark:bg-slate-800 flex-shrink-0 border border-[var(--outline)]">
          <img src={baseline.imageUrl} alt={baseline.label} className="w-full h-full object-cover" referrerPolicy="no-referrer" />
        </div>
        <div className="flex-1 min-w-0">
          <h4 className={cn("font-bold text-sm truncate", isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-on-surface dark:text-slate-200")}>{baseline.label}</h4>
          <div className="flex items-center gap-3 mt-0.5 text-[11px] text-[var(--on-surface-variant)]">
            <span className="flex items-center gap-1">{baseline.device === 'Mobile' ? <Smartphone className="w-3 h-3" /> : <Monitor className="w-3 h-3" />}{baseline.device}</span>
            <span className="flex items-center gap-1"><Globe className="w-3 h-3" />{baseline.browser}</span>
            <span className="flex items-center gap-1"><Calendar className="w-3 h-3" />{baseline.updatedAt}</span>
          </div>
        </div>
        <span className="text-[10px] px-2 py-0.5 rounded font-mono bg-slate-100 dark:bg-slate-800 text-[var(--on-surface-variant)] flex-shrink-0">{baseline.locale}</span>
        {isSelected && <CheckCircle2 className="w-4 h-4 text-primary flex-shrink-0" />}
      </div>
    );
  }

  return (
    <div 
      onClick={onClick}
      className={cn(
        "group bg-surface-container-lowest dark:bg-slate-900 rounded-xl border overflow-hidden transition-all cursor-pointer",
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
      <div className="p-4">
        <div className="flex justify-between items-start mb-2">
          <h4 className={cn("font-bold text-sm", isSelected ? "text-indigo-600 dark:text-indigo-400" : "text-on-surface dark:text-slate-200")}>{baseline.label}</h4>
          <span className={cn(
            "text-[10px] px-2 py-0.5 rounded font-mono",
            isSelected ? "bg-primary-container text-primary" : "bg-surface-container-high text-on-surface-variant"
          )}>
            {baseline.locale}
          </span>
        </div>
        <div className={cn(
          "flex items-center gap-4 text-xs",
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
          "text-[10px] mt-3 flex items-center gap-1",
          isSelected ? "text-primary/60" : "text-on-surface-variant/60"
        )}>
          <Calendar className="w-3 h-3" /> Updated {baseline.updatedAt}
        </p>
      </div>
    </div>
  );
}

function HistoryItem({ active, label, date }: { active?: boolean, label: string, date: string }) {
  return (
    <div className={cn(
      "flex items-center justify-between p-3 rounded-xl border transition-all",
      active 
        ? "bg-primary-container/30 border-primary/10" 
        : "hover:bg-surface-container-low border-transparent hover:border-outline-variant/10 cursor-pointer group"
    )}>
      <div className="flex items-center gap-3">
        <div className={cn("w-2 h-2 rounded-full", active ? "bg-primary" : "bg-outline-variant/40 group-hover:bg-primary/40")} />
        <div>
          <p className="text-xs font-bold text-on-surface">{label}</p>
          <p className="text-[10px] text-on-surface-variant">{date}</p>
        </div>
      </div>
      {active ? (
        <span className="text-[10px] font-mono text-primary font-bold">ACTIVE</span>
      ) : (
        <button className="text-[10px] font-bold text-primary opacity-0 group-hover:opacity-100 transition-opacity">REVERT</button>
      )}
    </div>
  );
}
