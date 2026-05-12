import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { 
  CheckCircle2, 
  XCircle, 
  History, 
  Sparkles, 
  Maximize2, 
  ChevronRight,
  ArrowUpCircle,
  AlertCircle,
  Loader2
} from 'lucide-react';
import { motion } from 'motion/react';
import { cn } from '../lib/utils';
import { useRole } from '../context/RoleContext';
import { ComparisonSlider } from '../components/ComparisonSlider';
import { clearApiCacheEntry } from '../hooks/useApiData';

export function ReportAnalysis() {
  const { id } = useParams();
  const { can, role } = useRole();
  const [data, setData] = React.useState<any>(null);
  const [loading, setLoading] = React.useState(true);
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [insight, setInsight] = React.useState<string>("Analyzing visual differences...");

  const fetchData = () => {
    if (!id) return;
    setLoading(true);
    fetch(`/api/run?id=${id}`)
      .then(res => res.json())
      .then(run => {
        setData(run);
        setLoading(false);
        setInsight(run.ai_explanation || "No local assessment available for this run.");
      })
      .catch(() => setLoading(false));
  };

  React.useEffect(() => {
    fetchData();
  }, [id]);

  const handleApprove = async () => {
    if (!id) return;
    setIsExecuting(true);
    try {
      const res = await fetch('/api/actions/review', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ 
          run: id, 
          decision: 'approved',
          reviewer: role === 'admin' ? 'Lead Scientist' : 'Technician'
        })
      });
      const result = await res.json();
      if (result.ok) {
        clearApiCacheEntry('/api/dashboard');
        fetchData();
      } else {
        alert(result.error || 'Failed to approve change');
      }
    } catch (err) {
      alert('Network failure');
    } finally {
      setIsExecuting(false);
    }
  };

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-12 h-12 text-primary animate-spin" />
          <p className="text-sm font-bold text-slate-400 uppercase tracking-widest">Compiling regression data...</p>
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-20 text-center font-bold">Laboratory Record Not Found</div>;

  const result = data.result || {};
  const status = data.status || 'UNKNOWN';
  const decision = data.decision || data.review || {};
  const severity = data.severity?.level || 'medium';
  const regions = result.regions || [];
  const history = data.decision_history || [];
  const isCompactDevice = /iphone|pixel|android|mobile/i.test(String(data.capture?.device || '').toLowerCase());
  const hasBinaryDiff = Number(result.diff_pixels || 0) > 0;

  return (
    <div className="h-full flex flex-col bg-white dark:bg-slate-950">
      {/* Header Info Section */}
      <div className="p-8 pb-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <Link to="/" className="text-primary dark:text-blue-400 hover:underline text-xs font-bold flex items-center gap-1 mr-4">
                ← Back to Dashboard
              </Link>
              <span className={cn(
                "px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-sm",
                status === 'PASS' ? "bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400" : "bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400"
              )}>
                {status === 'PASS' ? 'Passed' : 'Failed'}
              </span>
              <span className={cn(
                "px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-sm",
                severity === 'critical' || severity === 'high' ? "bg-red-500 text-white" : "bg-slate-100 dark:bg-slate-800 text-slate-500"
              )}>
                Severity: {severity}
              </span>
              {data.ai_assessment?.label && (
                <span className="px-2 py-0.5 bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 border border-indigo-100 dark:border-indigo-800 text-[10px] font-bold uppercase tracking-wider rounded-sm flex items-center gap-1">
                  <Sparkles className="w-3 h-3" /> {data.ai_assessment.label}
                </span>
              )}
              <span className="text-on-surface-variant dark:text-slate-400 text-xs flex items-center gap-1 ml-2">
                <History className="w-3 h-3" /> Run #{id}
              </span>
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-on-surface dark:text-slate-100 mb-4">
              Regression Analysis: {data.case_name || data.baseline_name}
            </h1>
            
            {/* AI Insight Banner */}
            <motion.div 
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="p-4 bg-slate-50 dark:bg-slate-900 rounded-xl border border-slate-100 dark:border-slate-800 flex gap-4 max-w-4xl shadow-sm"
            >
              <div className="w-10 h-10 rounded-lg bg-indigo-50 dark:bg-indigo-900/30 flex items-center justify-center shrink-0">
                <Sparkles className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <h4 className="text-sm font-semibold text-indigo-600 dark:text-indigo-400 mb-1">AI Automated Insight</h4>
                <p className="text-on-surface-variant dark:text-slate-300 text-sm leading-relaxed">{insight}</p>
              </div>
            </motion.div>
          </div>
        </div>
      </div>

      {/* Multi-Pane Workplace */}
      <div className="flex-1 flex overflow-hidden px-8 pb-8 gap-6">
            {/* Interactive Morph Slider for Mismatches */}
            {status !== 'PASS' && (
              <div className="mb-10">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-sm font-bold text-slate-400 uppercase tracking-widest">Interactive Morph Comparison</h3>
                  <span className="text-[10px] font-mono text-indigo-500 font-bold bg-indigo-50 dark:bg-indigo-900/30 px-2 py-0.5 rounded">A/B OVERLAY ACTIVE</span>
                </div>
                <ComparisonSlider 
                  baselineUrl={`/baseline/${data.baseline_name}/baseline.png`}
                  currentUrl={`/artifacts/${id}/current.png`}
                  labelBaseline="Original Baseline"
                  labelCurrent="Current Snapshot"
                  compact={isCompactDevice}
                />
              </div>
            )}

            <div className="bg-white dark:bg-slate-900 rounded-xl p-6 shadow-sm border border-slate-100 dark:border-slate-800">
              <h3 className="text-sm font-bold text-slate-400 uppercase tracking-widest mb-6">Screenshot Gallery</h3>
              <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
              {/* Baseline */}
              <ComparisonCard 
                label="Baseline" 
                version={`Ver: ${data.baseline_details?.current_version || '1.0.0'}`} 
                imageUrl={`/baseline/${data.baseline_name}/baseline.png`}
                compact={isCompactDevice}
              />
              {/* Current */}
              <ComparisonCard 
                label="Current" 
                status={status === 'PASS' ? 'MATCH' : 'MISMATCH'} 
                imageUrl={`/artifacts/${id}/current.png`} 
                isError={status !== 'PASS'}
                compact={isCompactDevice}
              />
              {/* Diff Overlay */}
              <ComparisonCard 
                label="Diff Overlay" 
                status="PIXEL VARIANCE" 
                imageUrl={`/artifacts/${id}/diff_overlay.png`} 
                isError={status !== 'PASS'}
                compact={isCompactDevice}
              />
            </div>
          </div>

          {/* Binary Diff */}
          <div className="bg-white dark:bg-slate-900 rounded-xl p-6 shadow-sm border border-slate-100 dark:border-slate-800">
            <div className="flex items-center justify-between mb-4">
              <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">Binary Diff Map</span>
            </div>
            <div
              className={cn(
                "bg-black rounded-lg overflow-hidden border border-slate-200 dark:border-slate-800 flex items-center justify-center",
                isCompactDevice ? "mx-auto w-full max-w-[360px] h-[680px]" : "w-full h-[320px] md:h-[360px]"
              )}
            >
              {hasBinaryDiff ? (
                <img 
                  src={`/artifacts/${id}/binary_diff.png`} 
                  alt="Binary Diff" 
                  className="w-full h-full object-contain grayscale brightness-200"
                  referrerPolicy="no-referrer"
                />
              ) : (
                <div className="flex h-full w-full flex-col items-center justify-center text-center px-6">
                  <div className="mb-3 rounded-full bg-emerald-500/15 px-3 py-1 text-[10px] font-bold uppercase tracking-[0.2em] text-emerald-300">
                    No visible diff
                  </div>
                  <p className="text-sm font-semibold text-slate-100">No pixel differences detected</p>
                  <p className="mt-2 max-w-xs text-xs leading-relaxed text-slate-400">
                    This run matched the baseline, so the binary diff map is intentionally empty.
                  </p>
                </div>
              )}
            </div>
        </div>

        {/* Side Panel (Inspector) */}
        <aside className="w-96 flex flex-col gap-6">
          {/* Decisions */}
          <div className="bg-slate-50 dark:bg-slate-900 rounded-2xl p-6 border border-slate-200 dark:border-slate-800 shadow-sm">
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-4">Current Decision</h3>
            <div className="flex flex-col gap-3">
              <span className={cn(
                "text-center py-2 px-4 rounded-lg text-xs font-bold uppercase tracking-widest mb-2 border",
                decision.status === 'approved' ? "bg-green-50 text-green-700 border-green-100" : 
                decision.status === 'rejected' ? "bg-red-50 text-red-700 border-red-100" :
                "bg-amber-50 text-amber-700 border-amber-100"
              )}>
                {decision.status || 'Pending Review'}
              </span>
              <button 
                onClick={handleApprove}
                disabled={!can('approve') || isExecuting || decision.status === 'approved'}
                className="w-full py-3 px-4 signature-gradient text-white font-semibold rounded-lg flex items-center justify-center gap-2 shadow-lg active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed">
                {isExecuting ? <Loader2 className="w-5 h-5 animate-spin" /> : <CheckCircle2 className="w-5 h-5" />}
                {decision.status === 'approved' ? 'Already Approved' : 'Approve Change'}
              </button>
            </div>
          </div>

          {/* Changed Regions */}
          <div className="flex-1 bg-white dark:bg-slate-900 rounded-2xl p-6 shadow-sm border border-slate-100 dark:border-slate-800 flex flex-col">
            <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-4">Changed Regions</h3>
            <div className="flex-1 overflow-y-auto space-y-4 pr-2 custom-scrollbar">
              {regions.length > 0 ? regions.map((r: any, idx: number) => (
                <RegionItem 
                  id={r.label || `region_${idx}`} 
                  type="Mismatch" 
                  description={`Visual variance detected at coordinates [${r.x}, ${r.y}] with dimensions ${r.width}x${r.height}.`} 
                />
              )) : (
                <div className="h-full flex flex-col items-center justify-center text-center opacity-40">
                  <CheckCircle2 className="w-8 h-8 mb-2" />
                  <p className="text-xs font-bold font-mono">NO REGIONS DETECTED</p>
                </div>
              )}
            </div>

            {/* Decision History */}
            <div className="mt-8 pt-6 border-t border-slate-100 dark:border-slate-800">
              <h3 className="text-sm font-bold uppercase tracking-widest text-slate-400 mb-4">Decision History</h3>
              <div className="space-y-4">
                {history.length > 0 ? history.map((h: any, idx: number) => (
                  <HistoryStep 
                    title={h.status === 'approved' ? 'Approved' : 'Rejected'} 
                    meta={`by ${h.decider || 'Unknown'} • ${new Date(h.timestamp).toLocaleString()}`} 
                    color={h.status === 'approved' ? 'bg-green-500' : 'bg-red-500'} 
                    comment={h.comment}
                  />
                )) : (
                  <HistoryStep 
                    title="Regression Detected" 
                    meta="Initial comparison completed" 
                    color="bg-primary" 
                  />
                )}
              </div>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function ComparisonCard({ label, version, status, imageUrl, isError, compact }: { label: string, version?: string, status?: string, imageUrl: string, isError?: boolean, compact?: boolean }) {
  return (
    <div className="bg-slate-50 dark:bg-slate-950 rounded-xl p-4 border border-slate-100 dark:border-slate-800">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">{label}</span>
        {version && <span className="text-[10px] text-slate-500">{version}</span>}
        {status && <span className={cn("text-[10px] font-semibold", isError ? "text-red-500 dark:text-red-400" : "text-primary dark:text-blue-400")}>{status}</span>}
      </div>
      <div
        className={cn(
          "bg-white dark:bg-slate-900 rounded-lg overflow-hidden border border-slate-100 dark:border-slate-800 flex items-center justify-center",
          compact ? "mx-auto w-full max-w-[340px] h-[620px]" : "w-full h-[260px] md:h-[300px]"
        )}
      >
        <img src={imageUrl} alt={label} className="w-full h-full object-contain" referrerPolicy="no-referrer" />
      </div>
    </div>
  );
}

function RegionItem({ id, type, description }: { id: string, type: string, description: string }) {
  return (
    <div className="group p-3 rounded-xl hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors border border-transparent hover:border-slate-200 dark:hover:border-slate-700">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-bold text-primary dark:text-blue-400">{id}</span>
        <span className="text-[10px] bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 px-1 rounded font-bold">{type}</span>
      </div>
      <p className="text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">{description}</p>
    </div>
  );
}

function HistoryStep({ title, meta, color, comment }: { title: string, meta: string, color: string, comment?: string }) {
  return (
    <div className="flex gap-3">
      <div className="w-0.5 bg-slate-100 dark:bg-slate-800 relative">
        <div className={cn("absolute top-0 -left-[3px] w-2 h-2 rounded-full shadow-sm", color)} />
      </div>
      <div>
        <p className="text-[11px] font-bold text-slate-900 dark:text-slate-100">{title}</p>
        <p className="text-[10px] text-slate-400 dark:text-slate-500">{meta}</p>
        {comment && <p className="text-[10px] mt-1 italic text-red-600 dark:text-red-400">"{comment}"</p>}
      </div>
    </div>
  );
}
