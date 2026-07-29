import { PageHeader } from '../components/ui/PageHeader';
import React from 'react';
import { Link } from 'react-router-dom';
import { 
  Camera, 
  GitBranch, 
  RefreshCw, 
  Diff,
  Search,
  Monitor,
  Smartphone,
  Globe,
  History,
  Zap,
  Play,
  X,
  Loader2,
  CheckCircle,
  AlertCircle,
  AlertTriangle,
  Lock
} from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { cn } from '../lib/utils';
import { useRole } from '../context/RoleContext';

type ActionTab = 'single' | 'multiple' | 'compare';

const tabs = [
  { id: 'single', label: 'Single Capture', icon: Camera },
  { id: 'multiple', label: 'Multiple Capture', icon: GitBranch },
  { id: 'compare', label: 'Run Comparison', icon: Diff },
] as const;

export function Actions() {
  const { can, role } = useRole();
  const [activeTab, setActiveTab] = React.useState<ActionTab>('single');
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [isPolling, setIsPolling] = React.useState(false);
  const [status, setStatus] = React.useState<{type: 'success' | 'error', message: string} | null>(null);
  const [comparisonResult, setComparisonResult] = React.useState<{
    runId: string;
    passed: boolean;
    mismatchPct: number;
    aiExplanation?: string;
  } | null>(null);
  const [batchResults, setBatchResults] = React.useState<Array<{
    name: string;
    runId?: string;
    passed?: boolean;
    mismatchPct?: number;
  }> | null>(null);
  const [baselineNames, setBaselineNames] = React.useState<string[]>([]);
  const [baselineError, setBaselineError] = React.useState(false);
  const pollIntervalRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(data => setBaselineNames((data.baselines || []).map((b: any) => b.name)))
      .catch(() => { setBaselineError(true); });
  }, []);

  React.useEffect(() => {
    return () => { if (pollIntervalRef.current) clearInterval(pollIntervalRef.current); };
  }, []);

  const handleAction = async (endpoint: string, payload: any) => {
    setIsExecuting(true);
    setStatus(null);
    setComparisonResult(null);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(payload)
      });
      const result = await response.json();
      if (result.ok) {
        if (result.task_id) {
          // Async task (e.g. Multiple Capture) — poll until done
          setStatus({ type: 'success', message: 'Crawl started in background. This may take a few minutes…' });
          setIsExecuting(false);
          setIsPolling(true);
          pollTaskStatus(result.task_id);
        } else {
          setStatus({ type: 'success', message: 'Action completed successfully.' });
          if (result.run_id) {
            setComparisonResult({
              runId: result.run_id,
              passed: result.passed,
              mismatchPct: result.mismatch_pct,
              aiExplanation: result.ai_explanation
            });
          }
          setIsExecuting(false);
        }
      } else {
        setStatus({ type: 'error', message: result.error || result.stderr || 'Action failed.' });
        setIsExecuting(false);
      }
    } catch (err) {
      setStatus({ type: 'error', message: 'Network error. Please try again.' });
      setIsExecuting(false);
    }
  };

  const pollTaskStatus = (taskId: string) => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/actions/task-status?id=${taskId}`, { credentials: 'include' });
        const data = await res.json();
        if (data.status === 'completed') {
          clearInterval(pollIntervalRef.current!);
          setIsPolling(false);
          setStatus({ type: 'success', message: `Crawl complete! Pages captured successfully.` });
        } else if (data.status === 'failed') {
          clearInterval(pollIntervalRef.current!);
          setIsPolling(false);
          setStatus({ type: 'error', message: `Crawl failed: ${data.stderr || 'Unknown error.'}` });
        }
        // still 'pending' or 'running' — keep polling
      } catch {
        clearInterval(pollIntervalRef.current!);
        setIsPolling(false);
      }
    }, 3000);
  };

  const loadBatchResults = async (names: string[]) => {
    try {
      const res = await fetch('/api/dashboard', { credentials: 'include' });
      const data = await res.json();
      const runs: any[] = data.runs || [];
      const results = names.map((name) => {
        // Runs are returned newest-first, so the first match per baseline
        // name is the run this batch comparison just produced.
        const match = runs.find((r) => (r.name ?? r.baseline_name) === name);
        const rawStatus = match ? (match.review_status ?? match.status) : undefined;
        return {
          name,
          runId: match?.id,
          passed: rawStatus ? rawStatus !== 'rejected' && rawStatus !== 'failed' : undefined,
          mismatchPct: match?.mismatch ?? match?.mismatch_pct,
        };
      });
      setBatchResults(results);
    } catch {
      // Best-effort lookup — leave batchResults empty if the dashboard fetch fails.
    }
  };

  const pollBatchTaskStatus = (taskId: string, names: string[]) => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
    pollIntervalRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/actions/task-status?id=${taskId}`, { credentials: 'include' });
        const data = await res.json();
        if (data.status === 'completed') {
          clearInterval(pollIntervalRef.current!);
          setIsPolling(false);
          setStatus({ type: 'success', message: `Batch comparison complete for ${names.length} baseline(s).` });
          await loadBatchResults(names);
        } else if (data.status === 'failed') {
          clearInterval(pollIntervalRef.current!);
          setIsPolling(false);
          setStatus({ type: 'error', message: `Batch comparison failed: ${data.stderr || 'Unknown error.'}` });
        }
        // still 'pending' or 'running' — keep polling
      } catch {
        clearInterval(pollIntervalRef.current!);
        setIsPolling(false);
      }
    }, 3000);
  };

  const handleCompareMultiple = async (names: string[]) => {
    setIsExecuting(true);
    setStatus(null);
    setComparisonResult(null);
    setBatchResults(null);
    try {
      const response = await fetch('/api/actions/compare-multiple', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ names })
      });
      const result = await response.json();
      if (result.ok && result.task_id) {
        setStatus({ type: 'success', message: `Batch comparison started for ${result.count ?? names.length} baseline(s) in the background…` });
        setIsExecuting(false);
        setIsPolling(true);
        pollBatchTaskStatus(result.task_id, names);
      } else {
        setStatus({ type: 'error', message: result.error || result.detail || 'Batch comparison failed to start.' });
        setIsExecuting(false);
      }
    } catch (err) {
      setStatus({ type: 'error', message: 'Network error. Please try again.' });
      setIsExecuting(false);
    }
  };


  return (
    <div className="p-8 min-h-screen transition-colors duration-300">
      <div className="max-w-4xl mx-auto space-y-12">
        <PageHeader title="System Actions" description="Capture, sync, and compare visual baselines." />

        {/* Tab Navigation */}
        <div role="tablist" className="inline-flex flex-wrap items-center gap-1.5 p-1.5 bg-[var(--surface)] border border-[var(--outline)] rounded-2xl shadow-sm">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id as ActionTab)}
              className={cn(
                "flex items-center gap-2.5 px-6 py-3 rounded-xl text-sm font-semibold transition-all duration-300",
                activeTab === tab.id 
                  ? "bg-primary text-white shadow-lg shadow-primary/20" 
                  : "text-[var(--on-surface-variant)] hover:text-primary hover:bg-slate-50 dark:hover:bg-slate-800"
              )}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Active Action Card */}
        <AnimatePresence mode="wait">
          <motion.div
            key={activeTab}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            className="bg-[var(--surface)] rounded-md border border-[var(--outline)] p-10 shadow-sm relative overflow-hidden"
          >
            {/* Background Accent */}
            <div className="absolute top-0 right-0 w-64 h-64 bg-accent/5 rounded-full -mr-32 -mt-32 blur-3xl" />

            <div className="relative z-10">
              <div className="flex items-center gap-4 mb-8">
                <div className="w-12 h-12 rounded-md bg-stone-50 dark:bg-zinc-800 flex items-center justify-center text-accent border border-slate-100 dark:border-slate-700 shadow-sm">
                  {React.createElement(tabs.find(t => t.id === activeTab)!.icon, { className: "w-6 h-6" })}
                </div>
                <div>
                  <h3 className="text-2xl font-bold text-[var(--on-surface)]">
                    {tabs.find(t => t.id === activeTab)?.label}
                  </h3>
                  <p className="text-xs text-[var(--on-surface-variant)] font-medium tracking-tight mt-0.5">
                    {activeTab === 'single' && "Capture a single page screenshot as a new baseline."}
                    {activeTab === 'multiple' && "Capture multiple pages from a target website."}
                    {activeTab === 'compare' && "Compare a baseline against a live URL."}
                  </p>
                </div>
              </div>

              <div className="space-y-8">
                {role === 'viewer' ? (
                  <div className="p-12 border-2 border-dashed border-[var(--outline)] rounded-md flex flex-col items-center justify-center text-center space-y-4">
                    <div className="p-4 bg-stone-50 dark:bg-zinc-800 rounded-full text-slate-300">
                      <Lock className="w-8 h-8" />
                    </div>
                    <div>
                      <h4 className="text-lg font-bold text-[var(--on-surface)]">Elevated Access Required</h4>
                      <p className="text-sm text-slate-500 max-w-xs mx-auto mt-1">Requires Developer or Admin access to run actions.</p>
                    </div>
                  </div>
                ) : (
                  <>
                    {activeTab === 'single' && <SingleCaptureForm onAction={(p) => handleAction('/api/actions/create-baseline', p)} disabled={isExecuting} />}
                    {activeTab === 'multiple' && <MultipleCaptureForm onAction={(p) => handleAction('/api/actions/create-multiple-baselines', p)} disabled={isExecuting} />}
                    {activeTab === 'compare' && <RunComparisonForm onAction={(p) => handleAction('/api/actions/compare', p)} onCompareMultiple={handleCompareMultiple} disabled={isExecuting} baselineNames={baselineNames} baselineError={baselineError} />}
                  </>
                )}
              </div>

              {/* Status Notifications */}
              <AnimatePresence>
                {status && (
                  <motion.div 
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: 'auto' }}
                    exit={{ opacity: 0, height: 0 }}
                    className={cn(
                      "mt-8 p-6 rounded-md flex items-center gap-4 border",
                      status.type === 'success' 
                        ? "bg-green-50 dark:bg-green-900/10 border-green-100 dark:border-green-800/20 text-green-800 dark:text-green-400" 
                        : "bg-red-50 dark:bg-red-900/10 border-red-100 dark:border-red-800/20 text-red-800 dark:text-red-400"
                    )}
                  >
                    {status.type === 'success' ? <CheckCircle className="w-5 h-5" /> : <AlertCircle className="w-5 h-5" />}
                    <p className="text-sm font-medium">{status.message}</p>
                    <button onClick={() => setStatus(null)} aria-label="Dismiss notification" className="ml-auto opacity-50 hover:opacity-100">
                      <X className="w-4 h-4" />
                    </button>
                  </motion.div>
                )}
              </AnimatePresence>

              {comparisonResult && (
                <motion.div 
                  initial={{ opacity: 0, scale: 0.95 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className={cn(
                    "mt-8 p-6 rounded-2xl border flex flex-col md:flex-row md:items-center justify-between gap-6 shadow-sm",
                    comparisonResult.passed 
                      ? "bg-emerald-50/50 dark:bg-emerald-950/10 border-emerald-200/50 dark:border-emerald-900/20" 
                      : "bg-red-50/50 dark:bg-red-950/10 border-red-200/50 dark:border-red-900/20"
                  )}
                >
                  <div className="space-y-2">
                    <div className="flex items-center gap-3">
                      <span className={cn(
                        "px-3 py-1 rounded-full text-xs font-bold uppercase tracking-wider",
                        comparisonResult.passed 
                          ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400" 
                          : "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                      )}>
                        {comparisonResult.passed ? 'Pass' : 'Fail'}
                      </span>
                      <span className="text-xs text-slate-500 font-semibold">
                        Mismatch: <span className="font-bold">{comparisonResult.mismatchPct.toFixed(2)}%</span>
                      </span>
                    </div>
                    {comparisonResult.aiExplanation && (
                      <p className="text-xs text-slate-600 dark:text-slate-400 leading-relaxed italic max-w-xl">
                        💡 AI Insight: {comparisonResult.aiExplanation}
                      </p>
                    )}
                  </div>
                  
                  <Link 
                    to={`/report/${comparisonResult.runId}`}
                    className={cn(
                      "px-5 py-3 rounded-xl text-xs font-bold transition-all text-center shrink-0 cursor-pointer shadow-sm",
                      comparisonResult.passed
                        ? "bg-emerald-600 hover:bg-emerald-700 text-white"
                        : "bg-red-600 hover:bg-red-700 text-white"
                    )}
                  >
                    View Detailed Report
                  </Link>
                </motion.div>
              )}

              {batchResults && batchResults.length > 0 && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="mt-8 space-y-3"
                >
                  <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-wider px-1">
                    Batch Comparison Results ({batchResults.length})
                  </h4>
                  <div className="space-y-2">
                    {batchResults.map((r) => (
                      <div
                        key={r.name}
                        className={cn(
                          "p-4 rounded-xl border flex items-center justify-between gap-4",
                          r.passed === undefined
                            ? "bg-slate-50 dark:bg-slate-900/50 border-slate-100 dark:border-slate-800"
                            : r.passed
                              ? "bg-emerald-50/50 dark:bg-emerald-950/10 border-emerald-200/50 dark:border-emerald-900/20"
                              : "bg-red-50/50 dark:bg-red-950/10 border-red-200/50 dark:border-red-900/20"
                        )}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <span className={cn(
                            "px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider shrink-0",
                            r.passed === undefined
                              ? "bg-stone-100 dark:bg-zinc-800 text-stone-500 dark:text-zinc-400"
                              : r.passed
                                ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400"
                                : "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
                          )}>
                            {r.passed === undefined ? 'Unknown' : r.passed ? 'Pass' : 'Fail'}
                          </span>
                          <span className="text-sm font-semibold text-[var(--on-surface)] truncate">{r.name}</span>
                          {r.mismatchPct !== undefined && (
                            <span className="text-xs text-slate-500 font-semibold shrink-0">
                              {r.mismatchPct.toFixed(2)}% mismatch
                            </span>
                          )}
                        </div>
                        {r.runId ? (
                          <Link
                            to={`/report/${r.runId}`}
                            className="px-3 py-2 rounded-lg text-xs font-bold text-accent hover:underline shrink-0"
                          >
                            View Report
                          </Link>
                        ) : (
                          <span className="text-xs text-slate-400 shrink-0">No run found</span>
                        )}
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}

              {/* Polling indicator */}
              {isPolling && (
                <div className="mt-4 flex items-center gap-2 text-sm text-[var(--on-surface-variant)]">
                  <span className="w-2 h-2 rounded-full bg-accent animate-pulse inline-block" />
                  In progress...
                </div>
              )}
            </div>

            {/* Loading Overlay */}
            <AnimatePresence>
              {isExecuting && (
                <motion.div
                  key="loading-overlay"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  className="absolute inset-0 z-50 bg-white/60 dark:bg-slate-950/60 backdrop-blur-sm flex flex-col items-center justify-center space-y-4 pointer-events-none"
                >
                  <div className="relative">
                    <div className="w-16 h-16 border-4 border-primary/20 rounded-full animate-spin" />
                    <Loader2 className="w-8 h-8 text-primary absolute inset-1/2 -ml-4 -mt-4 animate-spin" />
                  </div>
                  <div className="text-center">
                    <p className="text-lg font-bold text-[var(--on-surface)]">Running...</p>
                    <p className="text-xs text-slate-500 font-medium tracking-tight">Capturing screenshots, please wait...</p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </AnimatePresence>

      </div>
    </div>
  );
}

function SingleCaptureForm({ onAction, disabled }: { onAction: (p: any) => void, disabled: boolean }) {
  const [url, setUrl] = React.useState('');
  const [name, setName] = React.useState('');
  const [browser, setBrowser] = React.useState('Chrome');
  const [device, setDevice] = React.useState('Desktop');
  const [locale, setLocale] = React.useState('en-US');

  React.useEffect(() => {
    if (!url) return;
    try {
      const formattedUrl = url.startsWith('http') ? url : `https://${url}`;
      const u = new URL(formattedUrl);
      const hostPart = u.hostname.replace('www.', '');
      const pathPart = u.pathname.replace(/^\/|\/$/g, '').replace(/[^a-zA-Z0-9]+/g, '-');
      const suggestedName = pathPart ? `${hostPart}-${pathPart}` : hostPart;
      
      setName(prev => {
        if (prev === '' || prev.includes(hostPart) || prev.startsWith('suggested-')) {
          return suggestedName.slice(0, 64);
        }
        return prev;
      });
    } catch {
      // Invalid URL typed so far, ignore
    }
  }, [url]);

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
      <div className="space-y-6">
        <FormItem label="Target URL" placeholder="https://example.com/page" value={url} onChange={setUrl} />
        <FormItem label="Baseline Label" placeholder="e.g., Homepage - Mobile" value={name} onChange={setName} />
        <div className="grid grid-cols-3 gap-4">
          <FormSelect label="Browser" options={['Chrome', 'Safari', 'Firefox']} value={browser} onChange={setBrowser} />
          <FormSelect label="Device" options={['Desktop', 'iPhone 13', 'Pixel 5']} value={device} onChange={setDevice} />
          <FormSelect label="Locale" options={['en-US', 'zh-CN', 'ms-MY']} value={locale} onChange={setLocale} />
        </div>
      </div>
      <div className="bg-slate-50 dark:bg-slate-900/50 rounded-md border border-slate-100 dark:border-slate-800 p-6 flex flex-col justify-between">
        <div className="space-y-3">
          <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)]">How it works</h4>
          <p className="text-sm text-slate-600 dark:text-[var(--on-surface-variant)] leading-relaxed">
            Opens a headless browser, waits for network idle (500ms), then captures a full-page screenshot at the specified viewport.
          </p>
        </div>
        <button 
          onClick={() => onAction({ url, name, browser, device, locale })}
          disabled={disabled || !url || !name}
          className="w-full py-4 bg-primary text-white rounded-xl font-bold text-sm shadow-lg shadow-primary/20 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
        >
          <Camera className="w-4 h-4" /> Capture
        </button>
      </div>
    </div>
  );
}

function MultipleCaptureForm({ onAction, disabled }: { onAction: (p: any) => void, disabled: boolean }) {
  const [url, setUrl] = React.useState('');
  const [browser, setBrowser] = React.useState('Chrome');
  const [device, setDevice] = React.useState('Desktop');
  const [locale, setLocale] = React.useState('en-US');
  const [pageLimit, setPageLimit] = React.useState(30);

  return (
    <div className="space-y-8">
      <div className="p-6 bg-slate-50 dark:bg-slate-900/50 rounded-md border border-slate-100 dark:border-slate-800 space-y-6">
        <FormItem label="Website URL" placeholder="https://example.com" value={url} onChange={setUrl} />
        <div className="grid grid-cols-3 gap-4">
          <FormSelect label="Browser" options={['Chrome', 'Safari', 'Firefox']} value={browser} onChange={setBrowser} />
          <FormSelect label="Device" options={['Desktop', 'iPhone 13', 'Pixel 5']} value={device} onChange={setDevice} />
          <FormSelect label="Locale" options={['en-US', 'zh-CN', 'ms-MY']} value={locale} onChange={setLocale} />
        </div>
        <div className="space-y-2 max-w-xs">
          <label className="text-[10px] font-bold text-[var(--on-surface-variant)] px-1">Page Limit</label>
          <input
            type="number"
            min={1}
            max={100}
            value={pageLimit}
            onChange={e => setPageLimit(Math.max(1, Math.min(100, Number(e.target.value))))}
            className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all dark:text-slate-100"
          />
          <p className="text-[10px] text-[var(--on-surface-variant)] px-1">Maximum pages to crawl (1–100)</p>
        </div>
      </div>
      <button
        onClick={() => onAction({
          url,
          browser,
          device,
          locale,
          page_limit: pageLimit,
          overwrite: true
        })}
        disabled={disabled || !url}
        className="w-full py-4 bg-primary text-white rounded-xl font-bold text-sm shadow-lg shadow-primary/20 hover:bg-slate-800 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 cursor-pointer"
      >
        <Play className="w-4 h-4" /> Start Capture Run
      </button>
    </div>
  );
}



function RunComparisonForm({ onAction, onCompareMultiple, disabled, baselineNames, baselineError }: { onAction: (p: any) => void, onCompareMultiple: (names: string[]) => void, disabled: boolean, baselineNames: string[], baselineError?: boolean }) {
  const [baseline, setBaseline] = React.useState('');
  const [url, setUrl] = React.useState('');
  const [originalConfig, setOriginalConfig] = React.useState<{browser: string, device: string, locale: string} | null>(null);
  const [isMultiMode, setIsMultiMode] = React.useState(false);
  const [selectedBaselines, setSelectedBaselines] = React.useState<string[]>([]);

  React.useEffect(() => {
    if (!baseline || isMultiMode) return;
    // Guard against out-of-order responses: if the user picks baseline A then
    // quickly switches to baseline B, A's response can resolve after B's and
    // must not overwrite the config for the baseline actually selected now.
    let cancelled = false;
    fetch(`/api/baseline?id=${encodeURIComponent(baseline)}`)
      .then(res => res.json())
      .then(data => {
        if (cancelled) return;
        if (data && data.capture) {
          const capture = data.capture;
          if (capture.url) setUrl(capture.url);

          let b = capture.browser || 'Chrome';
          if (b.toLowerCase() === 'chromium') b = 'Chrome';
          if (b.toLowerCase() === 'webkit') b = 'Safari';
          if (b.toLowerCase() === 'firefox') b = 'Firefox';

          let d = capture.device || 'Desktop';
          let l = capture.locale || 'en-US';

          setOriginalConfig({
            browser: b,
            device: d,
            locale: l
          });
        }
      })
      .catch(err => console.error("Failed to fetch baseline details:", err));
    return () => { cancelled = true; };
  }, [baseline]);

  return (
    <div className="space-y-8">
      {baselineError && (
        <div className="p-4 bg-red-50 dark:bg-red-950/20 text-red-700 dark:text-red-400 border border-red-200 rounded-xl text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4" /> Failed to load baseline list. Please refresh or try again later.
        </div>
      )}

      <button
        type="button"
        onClick={() => {
          setIsMultiMode((prev) => !prev);
          // Switching modes: clear whichever selection belonged to the other mode
          // so a stale single/batch pick can't leak into the other flow.
          setBaseline('');
          setOriginalConfig(null);
          setSelectedBaselines([]);
        }}
        className={cn(
          "inline-flex items-center gap-2 px-4 py-2 rounded-full text-xs font-bold border transition-all cursor-pointer",
          isMultiMode
            ? "bg-accent/10 border-accent text-accent"
            : "bg-slate-50 dark:bg-slate-900/50 border-[var(--outline)] text-[var(--on-surface-variant)] hover:text-accent"
        )}
      >
        <span className={cn(
          "w-3.5 h-3.5 rounded-sm border flex items-center justify-center",
          isMultiMode ? "bg-accent border-accent" : "border-slate-300 dark:border-slate-600"
        )}>
          {isMultiMode && <CheckCircle className="w-3 h-3 text-white" />}
        </span>
        Compare Multiple Baselines
      </button>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <div className="space-y-6">
          {isMultiMode ? (
            <SearchableBaselineSelect
              label="Select Baselines"
              options={baselineNames}
              multiple
              values={selectedBaselines}
              onChangeMultiple={setSelectedBaselines}
            />
          ) : (
            <>
              <SearchableBaselineSelect label="Select Baseline" options={baselineNames} value={baseline} onChange={setBaseline} />
              <FormItem label="Website URL" placeholder="https://stage.example.com" value={url} onChange={setUrl} />
            </>
          )}
        </div>
        <div className="space-y-6">
          {isMultiMode ? (
            <div className="p-6 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800 space-y-2">
              <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-wider">Batch Comparison</h4>
              <p className="text-2xl font-bold text-[var(--on-surface)]">
                {selectedBaselines.length} baseline{selectedBaselines.length === 1 ? '' : 's'} selected
              </p>
              <p className="text-[10px] text-slate-500 leading-normal">
                Each baseline will be compared against its own stored URL and capture settings — the URL field is not used in batch mode.
              </p>
            </div>
          ) : originalConfig ? (
            <div className="p-6 bg-slate-50 dark:bg-slate-900/50 rounded-xl border border-slate-100 dark:border-slate-800 space-y-4">
              <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-wider">Baseline Configuration</h4>
              <div className="grid grid-cols-3 gap-4 text-xs font-semibold text-[var(--on-surface)]">
                <div className="p-3 bg-white dark:bg-slate-950 rounded-lg border border-[var(--outline)] text-center">
                  <div className="text-[9px] text-slate-400 font-bold uppercase tracking-wider mb-1">Browser</div>
                  {originalConfig.browser}
                </div>
                <div className="p-3 bg-white dark:bg-slate-950 rounded-lg border border-[var(--outline)] text-center">
                  <div className="text-[9px] text-slate-400 font-bold uppercase tracking-wider mb-1">Device</div>
                  {originalConfig.device}
                </div>
                <div className="p-3 bg-white dark:bg-slate-950 rounded-lg border border-[var(--outline)] text-center">
                  <div className="text-[9px] text-slate-400 font-bold uppercase tracking-wider mb-1">Locale</div>
                  {originalConfig.locale}
                </div>
              </div>
              <p className="text-[10px] text-slate-500 leading-normal">
                Comparison will automatically execute using these original parameters to ensure accurate results.
              </p>
            </div>
          ) : (
            <div className="h-[120px] flex items-center justify-center border-2 border-dashed border-[var(--outline)] rounded-xl text-xs text-slate-400">
              Select a baseline to view its target configuration
            </div>
          )}

          <div className="pt-4">
            {isMultiMode ? (
              <button
                onClick={() => onCompareMultiple(selectedBaselines)}
                disabled={disabled || selectedBaselines.length === 0}
                className="w-full py-4 bg-accent text-white rounded-xl font-bold text-sm shadow-lg shadow-accent/20 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 cursor-pointer"
              >
                <Zap className="w-4 h-4" /> Execute Batch Comparison
              </button>
            ) : (
              <button
                onClick={() => {
                  if (originalConfig) {
                    onAction({
                      name: baseline,
                      url,
                      browsers: [originalConfig.browser],
                      devices: [originalConfig.device],
                      locales: [originalConfig.locale]
                    });
                  }
                }}
                disabled={disabled || !baseline || !url || !originalConfig}
                className="w-full py-4 bg-accent text-white rounded-xl font-bold text-sm shadow-lg shadow-accent/20 hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2 cursor-pointer"
              >
                <Zap className="w-4 h-4" /> Execute Comparison
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function FormItem({ label, placeholder, value, onChange, isTextArea, type }: { label: string, placeholder: string, value: string, onChange: (v: string) => void, isTextArea?: boolean, type?: string }) {
  return (
    <div className="space-y-2">
      <label className="text-[10px] font-bold text-[var(--on-surface-variant)] px-1">{label}</label>
      {isTextArea ? (
        <textarea 
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all min-h-[120px] resize-none dark:text-slate-100"
        />
      ) : (
        <input 
          type={type || "text"}
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all dark:text-slate-100"
        />
      )}
    </div>
  );
}

function FormSelect({ label, options, value, onChange }: { label: string, options: string[], value: string, onChange: (v: string) => void }) {
  return (
    <div className="space-y-2">
      <label className="text-[10px] font-bold text-[var(--on-surface-variant)] px-1">{label}</label>
      <select 
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus:ring-4 focus:ring-accent/5 focus:border-accent transition-all cursor-pointer appearance-none dark:text-slate-100"
      >
        <option value="" disabled className="dark:bg-slate-900">Select...</option>
        {options.map(opt => <option key={opt} value={opt} className="dark:bg-slate-900">{opt}</option>)}
      </select>
    </div>
  );
}

function SearchableBaselineSelect({
  label,
  options,
  value,
  onChange,
  multiple = false,
  values = [],
  onChangeMultiple
}: {
  label: string,
  options: string[],
  value?: string,
  onChange?: (v: string) => void,
  multiple?: boolean,
  values?: string[],
  onChangeMultiple?: (v: string[]) => void
}) {
  const [isOpen, setIsOpen] = React.useState(false);
  const [search, setSearch] = React.useState('');
  const containerRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const handleOutsideClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleOutsideClick);
    return () => document.removeEventListener('mousedown', handleOutsideClick);
  }, []);

  const filtered = options.filter(opt =>
    opt.toLowerCase().includes(search.toLowerCase())
  );

  const toggleValue = (opt: string) => {
    if (!onChangeMultiple) return;
    if (values.includes(opt)) {
      onChangeMultiple(values.filter(v => v !== opt));
    } else {
      onChangeMultiple([...values, opt]);
    }
  };

  return (
    <div className="space-y-2 relative" ref={containerRef}>
      <label className="text-[10px] font-bold text-[var(--on-surface-variant)] px-1">{label}</label>

      {multiple && values.length > 0 && (
        <div className="flex flex-wrap gap-2 pb-1">
          {values.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1.5 pl-3 pr-2 py-1.5 rounded-full bg-accent/10 text-accent text-xs font-bold"
            >
              {v}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); toggleValue(v); }}
                aria-label={`Remove ${v}`}
                className="hover:bg-accent/20 rounded-full p-0.5 cursor-pointer"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div
        onClick={() => setIsOpen(true)}
        onKeyDown={(e) => {
          if (!isOpen && (e.key === 'Enter' || e.key === ' ')) {
            e.preventDefault();
            setIsOpen(true);
          }
        }}
        role="combobox"
        aria-expanded={isOpen}
        aria-haspopup="listbox"
        tabIndex={isOpen ? -1 : 0}
        className="w-full bg-white dark:bg-slate-950 border border-[var(--outline)] rounded-xl p-4 text-sm outline-none focus-within:ring-4 focus-within:ring-accent/5 focus-within:border-accent transition-all cursor-pointer flex items-center justify-between dark:text-slate-100 focus-visible:ring-4 focus-visible:ring-accent/20"
      >
        {isOpen ? (
          <input
            type="text"
            placeholder="Search baseline..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-transparent outline-none border-none p-0 text-sm dark:text-slate-100 placeholder-slate-400"
            autoFocus
          />
        ) : multiple ? (
          <span className={values.length > 0 ? "text-slate-900 dark:text-slate-100 font-semibold" : "text-slate-400"}>
            {values.length > 0 ? `${values.length} baseline${values.length === 1 ? '' : 's'} selected` : "Select baselines..."}
          </span>
        ) : (
          <span className={value ? "text-slate-900 dark:text-slate-100 font-semibold" : "text-slate-400"}>
            {value || "Select Baseline..."}
          </span>
        )}
        <Search className="w-4 h-4 text-slate-400 ml-2" />
      </div>

      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            role="listbox"
            className="absolute z-[100] w-full mt-2 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-xl max-h-60 overflow-y-auto"
          >
            {filtered.length > 0 ? (
              filtered.map((opt) => {
                const isSelected = multiple ? values.includes(opt) : opt === value;
                return (
                  <div
                    key={opt}
                    onClick={() => {
                      if (multiple) {
                        toggleValue(opt);
                        setSearch('');
                        // Keep the dropdown open so the user can pick more baselines.
                      } else {
                        onChange?.(opt);
                        setSearch('');
                        setIsOpen(false);
                      }
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        if (multiple) {
                          toggleValue(opt);
                          setSearch('');
                        } else {
                          onChange?.(opt);
                          setSearch('');
                          setIsOpen(false);
                        }
                      }
                    }}
                    role="option"
                    aria-selected={isSelected}
                    tabIndex={0}
                    className={cn(
                      "px-4 py-3 text-sm cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors flex items-center justify-between focus-visible:outline-none focus-visible:bg-slate-50 dark:focus-visible:bg-slate-800/50",
                      isSelected
                        ? "text-primary font-bold bg-primary/5 dark:bg-primary/10"
                        : "text-slate-700 dark:text-slate-300"
                    )}
                  >
                    {opt}
                    {isSelected && <CheckCircle className="w-4 h-4 text-primary" />}
                  </div>
                );
              })
            ) : (
              <div className="px-4 py-6 text-center text-xs text-slate-400">
                No baselines found
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
