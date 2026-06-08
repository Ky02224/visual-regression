import React from 'react';
import { Link, useParams, useLocation, useNavigate } from 'react-router-dom';
import { CheckCircle2, XCircle, ChevronDown, ChevronUp, Loader2, CheckCircle } from 'lucide-react';
import { cn } from '../lib/utils';
import { useRole } from '../context/RoleContext';
import { SideBySideComparison } from '../components/SideBySideComparison';
import { ComparisonSlider } from '../components/ComparisonSlider';
import { ComparisonToolbar, type ComparisonViewMode, type ZoomLevel } from '../components/ui/ComparisonToolbar';
import { DiffHighlightFrame } from '../components/ui/DiffHighlightFrame';
import { clearApiCacheEntry } from '../hooks/useApiData';
import { Button } from '../components/ui/Button';
import { Panel } from '../components/ui/Panel';
import { EmptyState } from '../components/ui/EmptyState';
import { ImageFrame } from '../components/ui/ImageFrame';
import { ChangeTypeBadge } from '../components/ui/ChangeTypeBadge';
import { ReviewStatusBadge } from '../components/ui/ReviewStatusBadge';
import { normalizeReviewStatus, mismatchPctClass } from '../lib/reviewStatus';

type ThumbView = 'baseline' | 'current' | 'diff';

export function ReportAnalysis() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const navState = location.state as { from?: string; suiteName?: string } | null;
  const { can, role, userName, userEmail } = useRole();
  const [data, setData] = React.useState<any>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(false);
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [insight, setInsight] = React.useState('');
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = React.useState(true);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [thumbView, setThumbView] = React.useState<ThumbView>('current');
  const [mainView, setMainView] = React.useState<ThumbView | 'compare'>('compare');
  const [viewMode, setViewMode] = React.useState<ComparisonViewMode>('side-by-side');
  const [showDiffOverlay, setShowDiffOverlay] = React.useState(false);
  const [zoom, setZoom] = React.useState<ZoomLevel>('fit');
  const [allRuns, setAllRuns] = React.useState<any[]>([]);
  const [isDrawing, setIsDrawing] = React.useState(false);
  const [localIgnoreRegions, setLocalIgnoreRegions] = React.useState<{ x: number; y: number; width: number; height: number }[]>([]);
  const [localIgnoreCss, setLocalIgnoreCss] = React.useState<string[]>([]);
  const [newCssSelector, setNewCssSelector] = React.useState('');
  const imageRef = React.useRef<HTMLImageElement>(null);
  const [dragStart, setDragStart] = React.useState<{ x: number; y: number } | null>(null);
  const [currentDragRect, setCurrentDragRect] = React.useState<{ x: number; y: number; width: number; height: number } | null>(null);

  React.useEffect(() => {
    if (data) {
      const parsed = (data.ignore_regions ?? []).map((r: any) => {
        if (Array.isArray(r)) {
          return { x: r[0], y: r[1], width: r[2], height: r[3] };
        }
        return r;
      });
      setLocalIgnoreRegions(parsed);
      setLocalIgnoreCss(data.ignore_css_selectors ?? []);
    }
  }, [data]);

  const saveIgnoreCssOnBackend = async (cssList: string[]) => {
    try {
      await fetch('/api/ignore-css-selectors', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: data?.baseline_name,
          ignore_css_selectors: cssList
        })
      });
      clearApiCacheEntry('/api/dashboard');
      fetchData();
    } catch (err) {
      console.error("Failed to save CSS ignore selectors", err);
    }
  };

  const addCssSelector = () => {
    const val = newCssSelector.trim();
    if (val && !localIgnoreCss.includes(val)) {
      const updated = [...localIgnoreCss, val];
      setLocalIgnoreCss(updated);
      saveIgnoreCssOnBackend(updated);
      setNewCssSelector('');
    }
  };

  const deleteCssSelector = (index: number) => {
    const updated = localIgnoreCss.filter((_, i) => i !== index);
    setLocalIgnoreCss(updated);
    saveIgnoreCssOnBackend(updated);
  };

  const saveIgnoreRegionsOnBackend = async (regions: typeof localIgnoreRegions) => {
    try {
      await fetch('/api/ignore-regions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: data?.baseline_name,
          ignore_regions: regions
        })
      });
      clearApiCacheEntry('/api/dashboard');
      // reload details
      fetchData();
    } catch (err) {
      console.error("Failed to save ignore regions", err);
    }
  };

  const deleteIgnoreRegion = (index: number) => {
    const updated = localIgnoreRegions.filter((_, i) => i !== index);
    setLocalIgnoreRegions(updated);
    saveIgnoreRegionsOnBackend(updated);
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDrawing || !imageRef.current) return;
    const rect = imageRef.current.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setDragStart({ x, y });
    setCurrentDragRect({ x, y, width: 0, height: 0 });
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDrawing || !dragStart || !imageRef.current) return;
    const rect = imageRef.current.getBoundingClientRect();
    const currentX = e.clientX - rect.left;
    const currentY = e.clientY - rect.top;

    const x = Math.min(dragStart.x, currentX);
    const y = Math.min(dragStart.y, currentY);
    const width = Math.abs(dragStart.x - currentX);
    const height = Math.abs(dragStart.y - currentY);

    setCurrentDragRect({ x, y, width, height });
  };

  const handleMouseUp = () => {
    if (!isDrawing || !dragStart || !currentDragRect || !imageRef.current) return;
    const img = imageRef.current;
    const rect = img.getBoundingClientRect();
    const scaleX = img.naturalWidth / rect.width;
    const scaleY = img.naturalHeight / rect.height;

    const newRegion = {
      x: Math.round(currentDragRect.x * scaleX),
      y: Math.round(currentDragRect.y * scaleY),
      width: Math.round(currentDragRect.width * scaleX),
      height: Math.round(currentDragRect.height * scaleY),
    };

    if (newRegion.width > 3 && newRegion.height > 3) {
      const updated = [...localIgnoreRegions, newRegion];
      setLocalIgnoreRegions(updated);
      saveIgnoreRegionsOnBackend(updated);
    }

    setDragStart(null);
    setCurrentDragRect(null);
  };

  const renderIgnoreRegionsOverlay = () => {
    if (!imageRef.current) return null;
    const img = imageRef.current;
    const rect = img.getBoundingClientRect();
    const scaleX = rect.width / img.naturalWidth;
    const scaleY = rect.height / img.naturalHeight;

    return (
      <div className="absolute inset-0 pointer-events-none select-none">
        {localIgnoreRegions.map((region, idx) => (
          <div
            key={idx}
            className="absolute border-2 border-red-500 bg-red-500/20 flex items-center justify-center pointer-events-auto"
            style={{
              left: `${region.x * scaleX}px`,
              top: `${region.y * scaleY}px`,
              width: `${region.width * scaleX}px`,
              height: `${region.height * scaleY}px`,
            }}
          >
            {isDrawing && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteIgnoreRegion(idx);
                }}
                className="bg-red-600 text-white rounded-full w-4 h-4 flex items-center justify-center text-[10px] hover:bg-red-700 shadow-md transform -translate-y-1/2 -translate-x-1/2 absolute top-0 left-0 cursor-pointer"
                title="Delete region"
              >
                ×
              </button>
            )}
          </div>
        ))}
        {currentDragRect && (
          <div
            className="absolute border-2 border-dashed border-red-400 bg-red-400/10"
            style={{
              left: `${currentDragRect.x}px`,
              top: `${currentDragRect.y}px`,
              width: `${currentDragRect.width}px`,
              height: `${currentDragRect.height}px`,
            }}
          />
        )}
      </div>
    );
  };

  React.useEffect(() => {
    fetch('/api/dashboard')
      .then(res => res.json())
      .then(d => { if (d && d.runs) setAllRuns(d.runs); })
      .catch(() => {});
  }, []);

  const relatedRuns = React.useMemo(() => {
    if (!data) return [];
    return allRuns.filter((r: any) => 
      r.build_id === data.build_id && 
      r.case_name === data.case_name
    );
  }, [allRuns, data]);

  const uniqueBrowsers = React.useMemo(() => {
    return Array.from(new Set(relatedRuns.map((r: any) => r.browser).filter(Boolean)));
  }, [relatedRuns]);

  const uniqueDevices = React.useMemo(() => {
    return Array.from(new Set(relatedRuns.map((r: any) => r.device || 'desktop').filter(Boolean)));
  }, [relatedRuns]);

  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

      if (e.key === 'd') {
        setShowDiffOverlay(prev => !prev);
      } else if (e.key === 'a') {
        submitReview('approved');
      } else if (e.key === 'r') {
        submitReview('rejected');
      } else if (e.key === ' ') {
        e.preventDefault();
        setMainView(prev => prev === 'baseline' ? 'current' : 'baseline');
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        // Switch to next/prev run in the same build
        const buildRuns = allRuns.filter((r: any) => r.build_id === data?.build_id);
        if (buildRuns.length <= 1) return;
        const currentIdx = buildRuns.findIndex((r: any) => r.id === id);
        if (currentIdx !== -1) {
          const nextIdx = e.key === 'ArrowRight' 
            ? (currentIdx + 1) % buildRuns.length 
            : (currentIdx - 1 + buildRuns.length) % buildRuns.length;
          navigate(`/report/${buildRuns[nextIdx].id}`, { state: navState });
        }
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [data, allRuns, id]);

  const fetchData = () => {
    if (!id) return;
    setLoading(true);
    setLoadError(false);
    fetch(`/api/run?id=${id}`)
      .then(res => { if (!res.ok) throw new Error('not found'); return res.json(); })
      .then(run => {
        setData(run);
        setInsight(run.ai_explanation || 'No automated summary for this run.');
        setLoading(false);
      })
      .catch(() => { setLoadError(true); setLoading(false); });
  };

  React.useEffect(() => { fetchData(); }, [id]);

  const submitReview = async (decision: 'approved' | 'rejected') => {
    if (!id) return;
    setIsExecuting(true);
    try {
      const res = await fetch('/api/actions/review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ run: id, decision, reviewer: userName || userEmail || role }),
      });
      const result = await res.json();
      if (result.ok) {
        clearApiCacheEntry('/api/dashboard');
        setActionError(null);
        fetchData();
      } else {
        setActionError(result.error || `Failed to ${decision === 'approved' ? 'approve' : 'reject'} change`);
      }
    } catch {
      setActionError('Network failure — please try again.');
    } finally {
      setIsExecuting(false);
    }
  };

  if (loading) {
    return (
      <div className="h-[calc(100vh-4rem)] flex items-center justify-center">
        <div className="w-full max-w-3xl px-6"><div className="animate-shimmer h-64 rounded-md" /></div>
      </div>
    );
  }

  if (loadError || !data) {
    return (
      <div className="h-[calc(100vh-4rem)] flex items-center justify-center p-6">
        <Panel className="max-w-md w-full">
          <EmptyState
            icon={<XCircle className="w-8 h-8" />}
            title="Report not found"
            description={`Run #${id} could not be loaded.`}
            action={<Link to="/"><Button variant="secondary">Back to dashboard</Button></Link>}
          />
        </Panel>
      </div>
    );
  }

  const result = data.result || {};
  const status = data.status || 'UNKNOWN';
  const decision = data.decision || data.review || {};
  const severity = data.severity?.level || 'medium';
  const regions = result.regions || [];
  const history = data.decision_history || [];
  const isCompactDevice = /iphone|pixel|android|mobile/i.test(String(data.capture?.device || '').toLowerCase());
  const aspectRatio = isCompactDevice ? '9/16' : '16/10';
  const hasBinaryDiff = Number(result.diff_pixels || 0) > 0;
  const mismatchRaw = Number(result.mismatch_pct ?? result.diff_percent ?? data.mismatch ?? 0);
  const diffPct = `${mismatchRaw.toFixed(2)}%`;
  const isPass = status === 'PASS';
  const isFailed = status === 'FAIL' || status === 'FAILED';

  const baselineUrl = `/baseline/${data.baseline_name}/baseline.png`;
  const currentUrl = `/artifacts/${id}/current.png`;
  const diffUrl = `/artifacts/${id}/diff_overlay.png`;


  const reviewStatus = normalizeReviewStatus(data.review_status ?? decision.status ?? status);
  const ignoreRegions: number[][] = data.ignore_regions ?? result.ignore_regions ?? [];

  return (
    <div className="review-layout bg-[var(--bg-main)]">
      {/* Left column */}
      <aside className="border-r border-[var(--outline)] overflow-y-auto bg-[var(--surface)]">
        <div className="p-4 space-y-4">
          <div>
            {navState?.from === 'suite' && navState.suiteName ? (
              <Link to={`/suite/${navState.suiteName}`} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">← Back to suite</Link>
            ) : (
              <Link to="/" className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">← Back to dashboard</Link>
            )}
          </div>
          <div className="space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <ReviewStatusBadge status={reviewStatus} />
              {!isPass && (
                <span className={cn('text-xs font-mono font-semibold px-2 py-0.5 rounded border border-[var(--outline)]', mismatchPctClass(mismatchRaw))}>
                  {diffPct} diff
                </span>
              )}
              <ChangeTypeBadge label={data.ai_assessment?.label ?? data.ai_label} />
            </div>
            <h1 className="text-base font-semibold leading-snug">{data.case_name || data.baseline_name}</h1>
            <p className="text-xs text-[var(--on-surface-variant)] font-mono">Run #{id}</p>
          </div>
          <Panel title="Ignore regions">
            <div className="space-y-3">
              <Button
                variant={isDrawing ? "approve" : "secondary"}
                className="w-full text-xs py-1"
                onClick={() => setIsDrawing(!isDrawing)}
              >
                {isDrawing ? "Save & Finish" : "✏️ Draw Ignore Regions"}
              </Button>
              {localIgnoreRegions.length > 0 ? (
                <ul className="space-y-1.5 max-h-32 overflow-y-auto">
                  {localIgnoreRegions.map((rect, idx) => (
                    <li key={idx} className="text-xs font-mono text-[var(--on-surface-variant)] flex items-center justify-between bg-stone-50 dark:bg-zinc-800 px-2 py-1 rounded">
                      <span>[{rect.x}, {rect.y}] · {rect.width}×{rect.height}px</span>
                      <button
                        onClick={() => deleteIgnoreRegion(idx)}
                        className="text-red-500 hover:text-red-700 font-bold ml-2 cursor-pointer"
                        title="Remove region"
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-[var(--on-surface-variant)] leading-relaxed">
                  No ignore regions yet. Click the edit button above to drag-and-draw regions directly over baseline screenshot.
                </p>
              )}
            </div>
          </Panel>
          <Panel title="Ignore CSS selectors">
            <div className="space-y-3">
              <div className="flex gap-1">
                <input
                  type="text"
                  placeholder="e.g. .dynamic-timer"
                  value={newCssSelector}
                  onChange={(e) => setNewCssSelector(e.target.value)}
                  className="flex-1 text-xs px-2 py-1 rounded border border-[var(--outline)] bg-[var(--surface)] text-[var(--on-surface)]"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      e.preventDefault();
                      addCssSelector();
                    }
                  }}
                />
                <Button variant="secondary" className="text-xs py-1 px-2" onClick={addCssSelector}>
                  Add
                </Button>
              </div>
              {localIgnoreCss.length > 0 ? (
                <ul className="space-y-1.5 max-h-32 overflow-y-auto">
                  {localIgnoreCss.map((sel, idx) => (
                    <li key={idx} className="text-xs font-mono text-[var(--on-surface-variant)] flex items-center justify-between bg-stone-50 dark:bg-zinc-800 px-2 py-1 rounded">
                      <span className="truncate max-w-[150px]">{sel}</span>
                      <button
                        onClick={() => deleteCssSelector(idx)}
                        className="text-red-500 hover:text-red-700 font-bold ml-2 cursor-pointer"
                        title="Remove selector"
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-[var(--on-surface-variant)] leading-relaxed">
                  Type a CSS selector and click Add to hide matching elements before capturing screens.
                </p>
              )}
            </div>
          </Panel>
          <Panel title="Changed regions">
            {regions.length > 0 ? (
              <ul className="space-y-2 max-h-48 overflow-y-auto">
                {regions.map((r: any, idx: number) => (
                  <li key={idx} className="text-xs p-2 rounded-md bg-stone-50 dark:bg-zinc-800/50 border border-[var(--outline)]">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-medium">{r.label || `Region ${idx + 1}`}</span>
                      {r.change_type && <ChangeTypeBadge label={r.change_type} />}
                    </div>
                    <p className="text-[var(--on-surface-variant)] mt-0.5">[{r.x}, {r.y}] · {r.width}×{r.height}px</p>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-xs text-[var(--on-surface-variant)]">No regions detected</p>
            )}
          </Panel>
          <div>
            <button type="button" onClick={() => setSummaryOpen(v => !v)} className="flex items-center justify-between w-full text-xs font-medium text-[var(--on-surface-variant)] mb-2">
              Change summary {summaryOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            {summaryOpen && (
              <Panel><p className="text-sm text-[var(--on-surface-variant)] leading-relaxed">{insight}</p></Panel>
            )}
          </div>
          <div>
            <button type="button" onClick={() => setHistoryOpen(v => !v)} className="flex items-center justify-between w-full text-xs font-medium text-[var(--on-surface-variant)] mb-2">
              Decision history {historyOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </button>
            {historyOpen && (
              <Panel>
                {history.length > 0 ? (
                  <ul className="space-y-3">
                    {history.map((h: any, idx: number) => (
                      <li key={idx} className="text-xs">
                        <p className="font-medium">{h.status === 'approved' ? 'Approved' : 'Rejected'}</p>
                        <p className="text-[var(--on-surface-variant)]">{h.decider || 'Unknown'} · {new Date(h.timestamp).toLocaleString()}</p>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-[var(--on-surface-variant)]">Initial comparison completed</p>
                )}
              </Panel>
            )}
          </div>
        </div>
      </aside>

      {/* Middle column — thumbnails */}
      <section className="border-r border-[var(--outline)] overflow-y-auto bg-stone-50 dark:bg-zinc-900/50 p-3 space-y-3">
        <p className="text-xs font-medium text-[var(--on-surface-variant)] px-1">Snapshots</p>
        {(['baseline', 'current', 'diff'] as ThumbView[]).map((view) => (
          <button
            key={view}
            type="button"
            onClick={() => { setThumbView(view); setMainView(view === 'diff' ? 'compare' : view); if (view === 'diff') setShowDiffOverlay(true); else setShowDiffOverlay(false); }}
            className={cn('snapshot-card w-full text-left', thumbView === view && 'snapshot-card-active')}
          >
            <div className="px-2 py-1.5 text-xs font-medium capitalize border-b border-[var(--outline)]">{view}</div>
            {view === 'diff' ? (
              <DiffHighlightFrame currentUrl={currentUrl} diffOverlayUrl={diffUrl} showDiff aspectRatio={aspectRatio} className="rounded-none border-0 min-h-[120px]" alt="diff" />
            ) : (
              <ImageFrame src={view === 'baseline' ? baselineUrl : currentUrl} alt={view} aspectRatio={aspectRatio} className="rounded-none border-0" />
            )}
          </button>
        ))}
      </section>

      {/* Right column — comparison workspace */}
      <section className="flex flex-col min-h-0 min-w-0 bg-[var(--surface)]">
        <div className="shrink-0 flex items-center justify-between gap-3 px-4 py-3 border-b border-[var(--outline)] bg-[var(--surface)]">
          <div className="min-w-0">
            <p className="text-sm font-semibold truncate">{data.case_name || data.baseline_name}</p>
            <p className="text-xs text-[var(--on-surface-variant)]">Severity: {severity}{!isPass && ` · ${diffPct} diff`}</p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <Button
              variant="secondary"
              size="lg"
              onClick={() => submitReview('rejected')}
              disabled={!can('approve') || isExecuting || decision.status === 'rejected'}
            >
              {decision.status === 'rejected' ? 'Changes requested' : 'Request changes'}
            </Button>
            <Button
              variant="approve"
              size="lg"
              onClick={() => submitReview('approved')}
              disabled={!can('approve') || isExecuting || decision.status === 'approved'}
            >
              {isExecuting ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
              {decision.status === 'approved' ? 'Already approved' : 'Approve change'}
            </Button>
          </div>
        </div>
        
        {relatedRuns.length > 1 && (
          <div className="shrink-0 flex items-center gap-4 px-4 py-2 bg-stone-50 dark:bg-zinc-900 border-b border-[var(--outline)] text-xs flex-wrap">
            {uniqueBrowsers.length > 1 && (
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-stone-400">Browser:</span>
                <div className="flex rounded-md overflow-hidden border border-[var(--outline)] bg-[var(--surface)]">
                  {uniqueBrowsers.map((b: any) => (
                    <button
                      key={b}
                      onClick={() => {
                        const target = relatedRuns.find((r: any) => r.browser === b && (r.device || 'desktop') === (data.device || 'desktop'));
                        if (target) navigate(`/report/${target.id}`, { state: navState });
                      }}
                      className={cn(
                        "px-2.5 py-1 font-medium border-r last:border-r-0 border-[var(--outline)] hover:bg-stone-100 dark:hover:bg-zinc-800",
                        data.browser === b ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/30 dark:text-indigo-400 font-bold" : "text-stone-500"
                      )}
                    >
                      {b}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {uniqueDevices.length > 1 && (
              <div className="flex items-center gap-1.5">
                <span className="font-semibold text-stone-400">Viewport:</span>
                <div className="flex rounded-md overflow-hidden border border-[var(--outline)] bg-[var(--surface)]">
                  {uniqueDevices.map((d: any) => (
                    <button
                      key={d}
                      onClick={() => {
                        const target = relatedRuns.find((r: any) => r.browser === data.browser && (r.device || 'desktop') === d);
                        if (target) navigate(`/report/${target.id}`, { state: navState });
                      }}
                      className={cn(
                        "px-2.5 py-1 font-medium border-r last:border-r-0 border-[var(--outline)] hover:bg-stone-100 dark:hover:bg-zinc-800",
                        (data.device || 'desktop') === d ? "bg-indigo-50 text-indigo-600 dark:bg-indigo-950/30 dark:text-indigo-400 font-bold" : "text-stone-500"
                      )}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!isPass && hasBinaryDiff && (
          <ComparisonToolbar
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            showDiff={showDiffOverlay}
            onShowDiffChange={setShowDiffOverlay}
            hasDiff={hasBinaryDiff}
            zoom={zoom}
            onZoomChange={setZoom}
          />
        )}
        {actionError && (
          <div className="shrink-0 mx-4 mt-2 rounded-md border border-red-200 bg-red-50 dark:bg-red-950/30 px-3 py-2 text-xs text-red-700 dark:text-red-400">{actionError}</div>
        )}
        <div className="flex-1 min-h-0 p-2 flex flex-col min-w-0">
          {isDrawing ? (
            <div className="flex-1 min-h-0 flex flex-col panel overflow-hidden">
              <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-medium bg-red-50 text-red-700 dark:bg-red-950/30 dark:text-red-400 flex justify-between items-center select-none">
                <span>Drawing Mode: Click and drag on the baseline image to draw ignore regions.</span>
                <span className="text-[10px] font-bold">DRAG TO DRAW</span>
              </div>
              <div
                className="flex-1 min-h-0 relative flex items-center justify-center p-4 bg-stone-100 dark:bg-zinc-900/50 overflow-auto"
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
              >
                <div className="relative inline-block max-w-full">
                  <img
                    ref={imageRef}
                    src={baselineUrl}
                    alt="Baseline Drawing Canvas"
                    className="max-h-[calc(100vh-16rem)] max-w-full block select-none pointer-events-none"
                    onLoad={() => {
                      // Trigger state refresh for alignment
                      setLocalIgnoreRegions(prev => [...prev]);
                    }}
                  />
                  {renderIgnoreRegionsOverlay()}
                </div>
              </div>
            </div>
          ) : isFailed && !hasBinaryDiff ? (
            <EmptyState icon={<XCircle className="w-8 h-8" />} title="Comparison failed" description="This run did not produce comparable screenshots." className="flex-1" />
          ) : isPass ? (
            <div className="flex flex-col flex-1 min-h-0 gap-3">
              <EmptyState icon={<CheckCircle2 className="w-8 h-8" />} title="No pixel differences" description="This run matched the baseline." />
              <div className="flex-1 min-h-0 max-w-2xl mx-auto w-full panel overflow-hidden">
                <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-medium">Baseline</div>
                <div className="p-3"><ImageFrame src={baselineUrl} alt="Baseline" aspectRatio={aspectRatio} /></div>
              </div>
            </div>
          ) : mainView === 'baseline' ? (
            <div className="flex-1 min-h-0 panel overflow-hidden flex flex-col cursor-pointer select-none" onClick={() => setMainView('current')}>
              <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-medium flex justify-between items-center bg-stone-50 dark:bg-zinc-900">
                <span>Baseline (Click to flash toggle)</span>
                <span className="text-[10px] text-indigo-500 font-mono">SPACE to toggle</span>
              </div>
              <div className="flex-1 min-h-0 relative"><div className="absolute inset-0"><ImageFrame src={baselineUrl} alt="Baseline" fill className="h-full w-full" /></div></div>
            </div>
          ) : mainView === 'current' ? (
            <div className="flex-1 min-h-0 panel overflow-hidden flex flex-col cursor-pointer select-none" onClick={() => setMainView('baseline')}>
              <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-medium flex justify-between items-center bg-stone-50 dark:bg-zinc-900">
                <span>Changes (Click to flash toggle)</span>
                <span className="text-[10px] text-indigo-500 font-mono">SPACE to toggle</span>
              </div>
              <div className="flex-1 min-h-0 relative"><div className="absolute inset-0"><DiffHighlightFrame currentUrl={currentUrl} diffOverlayUrl={diffUrl} showDiff={showDiffOverlay} zoom={zoom === 'fit' ? 1 : zoom} fill className="h-full w-full" alt="Changes" /></div></div>
            </div>
          ) : viewMode === 'slider' ? (
            <div className="flex-1 min-h-0 flex flex-col panel overflow-hidden">
              <ComparisonSlider
                baselineUrl={baselineUrl}
                currentUrl={currentUrl}
                diffOverlayUrl={diffUrl}
                showDiff={showDiffOverlay}
                zoom={zoom}
                labelBaseline="Baseline"
                labelCurrent="Changes"
              />
            </div>
          ) : (
            <SideBySideComparison
              baselineUrl={baselineUrl}
              currentUrl={currentUrl}
              diffOverlayUrl={diffUrl}
              showDiffOverlay={showDiffOverlay}
              zoom={zoom}
              labelBaseline="Baseline"
              labelCurrent="Changes"
              className="flex-1 min-h-0"
            />
          )}
        </div>
      </section>
    </div>
  );
}
