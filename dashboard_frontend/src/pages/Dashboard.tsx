import React from 'react';
import { Link } from 'react-router-dom';
import { 
  Plus, 
  History, 
  AlertTriangle, 
  CheckCircle2,
  Filter,
  Smartphone,
  Monitor,
  ChevronRight,
  ChevronDown,
  X,
  Sparkles,
  Globe,
  Layers,
  Search
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { TestRun } from '../types';
import { useRole } from '../context/RoleContext';

interface GroupedRuns {
  url: string;
  runs: TestRun[];
}

export function Dashboard() {
  const { can, accessKey } = useRole();
  const [dashboardData, setDashboardData] = React.useState<any>(null);
  const [loading, setLoading] = React.useState(true);
  const [groupedRuns, setGroupedRuns] = React.useState<GroupedRuns[]>([]);
  
  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => {
        setDashboardData(data);
        
        // Group runs by url
        const groups: Record<string, TestRun[]> = {};
        const runs = data.runs || [];
        runs.forEach((r: any) => {
          const urlStr = r.url || 'Unknown';
          if (!groups[urlStr]) groups[urlStr] = [];
          
          let status: TestRun['status'] = 'passed';
          if (r.status === 'FAIL') status = 'failed';
          if (r.decision_status === 'pending') status = 'attention';
          
          // Map backend severity to frontend matching type
          let mappedSeverity: TestRun['severity'] = undefined;
          if (r.severity && typeof r.severity === 'object' && r.severity.level) {
              const level = String(r.severity.level).toLowerCase();
              if (['critical', 'high', 'medium', 'low'].includes(level)) {
                  mappedSeverity = level as 'critical' | 'high' | 'medium' | 'low';
              }
          }

          groups[urlStr].push({
            id: r.run,
            name: r.case_name || r.baseline_name || r.run,
            status,
            mismatch: r.mismatch_pct || 0,
            lastRun: r.decided_at || r.run,
            browser: r.browser || 'Unknown',
            device: r.device || 'Unknown',
            locale: r.locale || 'Unknown',
            aiInsight: r.ai_explanation,
            aiLabel: r.ai_label,
            severity: mappedSeverity
          });
        });
        
        const arr = Object.keys(groups).map(url => ({ url, runs: groups[url] }));
        setGroupedRuns(arr);
        setLoading(false);
      });
  }, []);

  const [selectedRun, setSelectedRun] = React.useState<TestRun | null>(null);
  const [expandedUrls, setExpandedUrls] = React.useState<string[]>([]);
  
  // Set initial selected and expanded when data loads
  React.useEffect(() => {
    if (groupedRuns.length > 0 && expandedUrls.length === 0) {
      setExpandedUrls([groupedRuns[0].url]);
      if (!selectedRun && groupedRuns[0].runs.length > 0) {
        setSelectedRun(groupedRuns[0].runs[0]);
      }
    }
  }, [groupedRuns]);

  // Filter States
  const [websiteFilter, setWebsiteFilter] = React.useState('All');
  const [deviceFilter, setDeviceFilter] = React.useState('All');
  const [localeFilter, setLocaleFilter] = React.useState('All');
  const [statusFilter, setStatusFilter] = React.useState('All');
  const [searchQuery, setSearchQuery] = React.useState('');

  const filteredGroups = React.useMemo(() => {
    return groupedRuns.map(group => ({
      ...group,
      runs: group.runs.filter(run => {
        const matchesSearch = run.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                             group.url.toLowerCase().includes(searchQuery.toLowerCase());
        const matchesStatus = statusFilter === 'All' || 
                             (statusFilter === 'Failed' && run.status === 'failed') ||
                             (statusFilter === 'Approved' && run.status === 'passed') ||
                             (statusFilter === 'Attention' && run.status === 'attention');
        return matchesSearch && matchesStatus;
      })
    })).filter(group => group.runs.length > 0);
  }, [groupedRuns, searchQuery, statusFilter]);

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
          const matchesSearch = searchQuery === '' || 
                               run.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
                               group.url.toLowerCase().includes(searchQuery.toLowerCase());
          const matchesWebsite = websiteFilter === 'All' || group.url === websiteFilter;
          const matchesDevice = deviceFilter === 'All' || run.device === deviceFilter;
          const matchesLocale = localeFilter === 'All' || run.locale === localeFilter;
          const matchesStatus = statusFilter === 'All' || run.status === statusFilter.toLowerCase();
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
        <div className="h-12 bg-slate-200/50 rounded-xl w-1/4"></div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-32 bg-slate-200/50 rounded-2xl"></div>)}
        </div>
        <div className="h-96 bg-slate-200/50 rounded-2xl"></div>
      </div>
    );
  }

  const m = dashboardData?.metrics || {};

  return (
    <div className="p-8 max-w-7xl mx-auto corporate-grid min-h-screen transition-colors duration-300">
      <header className="mb-12 flex justify-between items-end border-b border-slate-200 dark:border-slate-800 pb-8">
        <div>
          <h2 className="text-3xl font-bold text-slate-900 dark:text-slate-100 mb-2">Visual Change Status</h2>
          <p className="text-slate-500 font-medium">
            Monitoring architectural regression across <span className="text-accent font-bold">{m.baseline_count || 0} baselines</span>.
          </p>
        </div>
        <div className="flex gap-2">
        </div>
      </header>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-12">
        <StatCard icon={<Monitor className="w-5 h-5" />} label="Active" value={String(m.baseline_count || 0)} subValue="Baselines" />
        <StatCard icon={<History className="w-5 h-5" />} label="Total Runs" value={String(m.run_count || 0)} subValue="All Time" />
        <StatCard 
          icon={<AlertTriangle className="w-5 h-5" />} 
          label="Priority" 
          value={String(m.pending_decisions || 0)} 
          subValue="Needs Attention" 
          isAlert={!!m.pending_decisions}
        />
        <StatCard icon={<CheckCircle2 className="w-5 h-5" />} label="Overall" value={String(m.approved_decisions || 0)} subValue="Approved decisions" />
      </div>

      <div className="space-y-12">
        {/* Results Accordion */}
        <div className="space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
            <div className="flex items-center gap-4 flex-1">
              <h3 className="text-xs font-bold uppercase tracking-[0.2em] text-slate-400">Execution Log</h3>
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                <input 
                  type="text"
                  placeholder="Search case name or URL..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full pl-9 pr-4 py-2 bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs outline-none focus:ring-2 focus:ring-accent/20 transition-all font-medium"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <FilterSelect 
                label="Website" 
                options={websiteOptions} 
                value={websiteFilter} 
                onChange={setWebsiteFilter} 
              />
              <FilterSelect 
                label="Device" 
                options={deviceOptions} 
                value={deviceFilter} 
                onChange={setDeviceFilter} 
              />
              <FilterSelect 
                label="Locale" 
                options={localeOptions} 
                value={localeFilter} 
                onChange={setLocaleFilter} 
              />
              <FilterSelect 
                label="Status" 
                options={['All', 'Failed', 'Passed', 'Attention']} 
                value={statusFilter} 
                onChange={setStatusFilter} 
              />
            </div>
          </div>
          
          <div className="grid grid-cols-1 gap-4">
            {filteredGroupedRuns.map((group) => (
              <div key={group.url} className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 overflow-hidden shadow-sm transition-all hover:border-accent/30 dark:hover:border-accent/50">
                <button 
                  onClick={() => toggleUrl(group.url)}
                  className="w-full px-6 py-5 flex items-center justify-between hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                >
                  <div className="flex items-center gap-4">
                    <div className="w-10 h-10 rounded-xl bg-slate-100 dark:bg-slate-800 flex items-center justify-center text-slate-400">
                      <Globe className="w-5 h-5" />
                    </div>
                    <div className="text-left">
                      <span className="font-bold text-slate-900 dark:text-slate-100 text-sm block">{group.url}</span>
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">
                        {group.runs.length} Active Nodes
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-6">
                    {group.runs.some(r => r.status === 'failed') && (
                      <div className="flex -space-x-2">
                        {[1, 2].map(i => (
                          <div key={i} className="w-6 h-6 rounded-full border-2 border-white bg-red-50 flex items-center justify-center">
                            <AlertTriangle className="w-3 h-3 text-red-600" />
                          </div>
                        ))}
                      </div>
                    )}
                    {expandedUrls.includes(group.url) ? <ChevronDown className="w-5 h-5 text-slate-300" /> : <ChevronRight className="w-5 h-5 text-slate-300" />}
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
                            onClick={() => setSelectedRun(run)}
                            className={cn(
                              "px-6 py-4 flex items-center justify-between cursor-pointer transition-all hover:bg-slate-50 dark:hover:bg-slate-800/30 group",
                              selectedRun?.id === run.id ? "bg-blue-50/50 dark:bg-slate-800 border-l-4 border-l-accent" : "border-l-4 border-l-transparent"
                            )}
                          >
                            <div className="flex items-center gap-4">
                              <div className="p-2 rounded-lg bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-700 shadow-sm group-hover:scale-110 transition-transform">
                                {run.device.includes('iPhone') ? <Smartphone className="w-4 h-4 text-slate-400" /> : <Monitor className="w-4 h-4 text-slate-400" />}
                              </div>
                              <div>
                                <div className="flex items-center gap-2">
                                  <p className="font-bold text-slate-900 dark:text-slate-200 text-sm">{run.name}</p>
                                  {run.aiLabel && (
                                    <span className="flex items-center gap-1 px-1.5 py-0.5 bg-indigo-50 text-indigo-600 rounded text-[9px] font-bold uppercase tracking-tighter border border-indigo-100">
                                      <Sparkles className="w-2.5 h-2.5" />
                                      {run.aiLabel}
                                    </span>
                                  )}
                                </div>
                                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-tight">{run.browser} • {run.device}</p>
                              </div>
                            </div>
                            <div className="flex items-center gap-8">
                              <div className="text-right">
                                <p className={cn("text-sm font-bold font-mono tracking-tighter", run.status === 'failed' ? "text-red-600" : "text-slate-500")}>
                                  {run.mismatch}%
                                </p>
                                <p className="text-[10px] text-slate-400 uppercase font-bold tracking-tight">Mismatch</p>
                              </div>
                              <StatusBadge status={run.status} />
                            </div>
                          </div>
                        ))}
                      </div>
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            ))}
          </div>

          {!showAll && filteredGroupedRuns.length >= LIST_LIMIT && (
            <div className="flex justify-center mt-12">
              <button 
                onClick={() => setShowAll(true)}
                className="group relative px-8 py-3 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl text-xs font-bold uppercase tracking-[0.2em] text-slate-400 hover:text-accent hover:border-accent transition-all overflow-hidden"
              >
                <div className="relative z-10 flex items-center gap-2">
                  <RotateCcw className="w-3.5 h-3.5 group-hover:rotate-180 transition-transform duration-500" />
                  Load Complete History
                </div>
              </button>
            </div>
          )}
        </div>

        {/* Detail Panel */}
        <AnimatePresence mode="wait">
          {selectedRun && (
            <motion.div 
              key={selectedRun.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 p-8 shadow-sm relative overflow-hidden"
            >
              <div className="absolute top-0 right-0 p-8">
                <button 
                  onClick={() => setSelectedRun(null)}
                  className="w-10 h-10 rounded-full hover:bg-slate-50 dark:hover:bg-slate-800 flex items-center justify-center text-slate-300 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div className="mb-8">
                <div className="flex items-center gap-3 mb-3">
                  <span className="px-2 py-1 bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400 rounded text-[10px] font-bold uppercase tracking-widest font-mono">
                    Node ID: {selectedRun.id.padStart(4, '0')}
                  </span>
                  {selectedRun.severity === 'high' && (
                    <span className="px-2 py-1 bg-red-50 text-red-600 rounded text-[10px] font-bold uppercase tracking-widest">
                      High Priority
                    </span>
                  )}
                  {selectedRun.aiLabel && (
                    <span className="px-2 py-1 bg-indigo-50 text-indigo-600 rounded text-[10px] font-bold uppercase tracking-widest border border-indigo-100 flex items-center gap-1.5">
                      <Sparkles className="w-3 h-3" />
                      AI Insight: {selectedRun.aiLabel}
                    </span>
                  )}
                </div>
                <h3 className="text-2xl font-bold text-slate-900 dark:text-slate-100">{selectedRun.name}</h3>
                {selectedRun.aiInsight && (
                  <p className="mt-2 text-sm text-slate-500 font-medium italic">
                    "{selectedRun.aiInsight}"
                  </p>
                )}
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 mb-8">
                <div className="lg:col-span-2">
                  <ScreenshotSlider 
                    baselineSrc={`/baseline/${selectedRun.name}/baseline.png`} 
                    actualSrc={`/artifacts/${selectedRun.id}/current.png`} 
                    compact={/iphone|pixel|android|mobile/i.test((selectedRun.device || '').toLowerCase())}
                  />
                </div>
                <div className="lg:col-span-1">
                  <ComparisonImage
                    label="Difference Highlight"
                    src={`/artifacts/${selectedRun.id}/diff_overlay.png`}
                    isDiff
                    compact={/iphone|pixel|android|mobile/i.test((selectedRun.device || '').toLowerCase())}
                  />
                </div>
              </div>

              <div className="p-6 bg-slate-50 dark:bg-slate-900/50 rounded-2xl border border-slate-100 dark:border-slate-800 grid grid-cols-1 md:grid-cols-2 gap-8 mb-8">
                <div className="flex justify-between items-center md:col-span-1">
                  <InfoItem label="Mismatch Score" value={`${selectedRun.mismatch}%`} valueClass={selectedRun.status === 'failed' ? 'text-red-600 text-xl' : 'text-amber-600 text-xl'} />
                </div>
                <div className="grid grid-cols-2 gap-4 md:col-span-1">
                  <InfoItem label="Browser" value={selectedRun.browser} />
                  <InfoItem label="Device" value={selectedRun.device} />
                </div>
              </div>

              <div className="flex gap-3 justify-end">
                {can('approve') && (
                  <button 
                    onClick={() => {
                      fetch('/api/actions/review', {
                        method: 'POST',
                        headers: {
                          'Content-Type':'application/json',
                          'X-Access-Key': accessKey || ''
                        },
                        body: JSON.stringify({ 
                          run: selectedRun.id, 
                          decision: 'approved',
                          reviewer: 'Admin'
                        })
                      }).then(() => window.location.reload());
                    }}
                    className="px-8 py-3 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-200 font-bold text-sm rounded-xl hover:bg-slate-50 dark:hover:bg-slate-700 transition-all">
                    Approve
                  </button>
                )}
                <Link 
                  to={`/report/${selectedRun.id}`}
                  className="px-8 py-3 bg-primary text-white rounded-xl shadow-lg shadow-primary/20 hover:bg-slate-800 transition-all font-bold text-sm text-center"
                >
                  Deep Analysis
                </Link>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

function ScreenshotSlider({ baselineSrc, actualSrc, compact }: { baselineSrc: string, actualSrc: string, compact?: boolean }) {
  const [sliderPos, setSliderPos] = React.useState(50);
  const containerRef = React.useRef<HTMLDivElement>(null);

  const handleMove = (e: React.MouseEvent | React.TouchEvent) => {
    if (!containerRef.current) return;
    const { left, width } = containerRef.current.getBoundingClientRect();
    const clientX = 'touches' in e ? e.touches[0].clientX : (e as React.MouseEvent).clientX;
    const x = Math.max(0, Math.min(clientX - left, width));
    setSliderPos((x / width) * 100);
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-1">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Baseline vs Current</span>
      </div>
      <div 
        ref={containerRef}
        onMouseMove={handleMove}
        onTouchMove={handleMove}
        className={cn(
          "relative rounded-xl overflow-hidden border border-slate-200 bg-slate-100 cursor-ew-resize group select-none",
          compact
            ? "mx-auto w-full max-w-[260px] h-[500px] sm:max-w-[280px] sm:h-[540px]"
            : "w-full h-[320px] md:h-[380px]"
        )}
      >
        <img className="absolute inset-0 w-full h-full object-contain pointer-events-none" src={actualSrc} alt="Current" referrerPolicy="no-referrer" />
        <div 
          className="absolute inset-y-0 left-0 overflow-hidden" 
          style={{ width: `${sliderPos}%` }}
        >
          <img
            className="absolute inset-y-0 left-0 w-full h-full object-contain max-w-none pointer-events-none"
            style={{ width: containerRef.current?.getBoundingClientRect().width || '100%' }}
            src={baselineSrc}
            alt="Baseline"
            referrerPolicy="no-referrer"
          />
        </div>
        <div 
          className="absolute inset-y-0 bg-white shadow-lg w-0.5"
          style={{ left: `${sliderPos}%` }}
        >
          <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-6 h-6 bg-white rounded-full border border-slate-200 shadow-sm flex items-center justify-center pointer-events-none">
            <div className="w-0.5 h-3 bg-slate-300 rounded-full mx-0.5" />
            <div className="w-0.5 h-3 bg-slate-300 rounded-full mx-0.5" />
          </div>
        </div>
      </div>
    </div>
  );
}

function ComparisonImage({ label, src, isDiff, compact }: { label: string, src: string, isDiff?: boolean, compact?: boolean }) {
  return (
    <div className="space-y-2 h-full flex flex-col">
      <div className="flex items-center justify-between px-1">
        <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{label}</span>
      </div>
      <div className={cn(
        "flex-1 rounded-xl overflow-hidden border group cursor-zoom-in relative",
        compact ? "mx-auto w-full max-w-[260px] min-h-[500px] sm:max-w-[280px] sm:min-h-[540px]" : "min-h-[320px] md:min-h-[380px]",
        isDiff ? "bg-slate-900 border-slate-800" : "bg-slate-100 border-slate-200"
      )}>
        <img className="w-full h-full object-contain transition-transform duration-500 group-hover:scale-105" src={src} alt={label} referrerPolicy="no-referrer" />
        <div className="absolute inset-0 bg-primary/0 group-hover:bg-primary/5 transition-colors" />
      </div>
    </div>
  );
}

function StatCard({ icon, label, value, subValue, isAlert }: { icon: React.ReactNode, label: string, value: string, subValue: string, isAlert?: boolean }) {
  return (
    <div className={cn(
      "bg-white dark:bg-slate-900 p-8 rounded-2xl border border-slate-200 dark:border-slate-800 transition-all hover:shadow-xl dark:shadow-slate-900/50 hover:-translate-y-1 group",
      isAlert && "border-t-4 border-t-red-600"
    )}>
      <div className="flex justify-between items-start mb-6">
        <div className={cn(
          "w-12 h-12 rounded-xl flex items-center justify-center transition-colors bg-slate-50 dark:bg-slate-800 text-slate-400 group-hover:bg-accent group-hover:text-white",
          isAlert && "group-hover:bg-red-600"
        )}>
          {icon}
        </div>
        <span className={cn("text-[10px] font-bold uppercase tracking-[0.2em] text-slate-300", isAlert && "text-red-600/50 group-hover:text-red-600")}>
          {label}
        </span>
      </div>
      <div>
        <span className="text-4xl font-bold text-slate-900 dark:text-white tracking-tighter font-mono">{value}</span>
        <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mt-2">{subValue}</p>
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
        <div className="flex items-center gap-2 px-3 py-1 bg-error-container/20 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-error animate-pulse shadow-[0_0_8px_rgba(255,0,0,0.6)]" />
          <span className="text-error text-[10px] font-bold uppercase tracking-widest">Failed</span>
        </div>
      );
    case 'attention':
      return (
        <div className="flex items-center gap-2 px-3 py-1 bg-amber-50 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-amber-500" />
          <span className="text-amber-700 text-[10px] font-bold uppercase tracking-widest">Attention</span>
        </div>
      );
    case 'passed':
      return (
        <div className="flex items-center gap-2 px-3 py-1 bg-blue-50 rounded-full">
          <div className="w-1.5 h-1.5 rounded-full bg-accent shadow-[0_0_8px_rgba(37,99,235,0.6)]" />
          <span className="text-accent text-[10px] font-bold uppercase tracking-widest">Passed</span>
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
