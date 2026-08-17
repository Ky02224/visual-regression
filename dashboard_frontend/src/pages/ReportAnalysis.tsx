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
import { useSSE } from '../hooks/useSSE';
import { Panel } from '../components/ui/Panel';
import { EmptyState } from '../components/ui/EmptyState';
import { ImageFrame } from '../components/ui/ImageFrame';
import { ChangeTypeBadge } from '../components/ui/ChangeTypeBadge';
import { ReviewStatusBadge } from '../components/ui/ReviewStatusBadge';
import { normalizeReviewStatus, mismatchPctClass } from '../lib/reviewStatus';
import { api } from '../services/apiClient';

type ThumbView = 'baseline' | 'current' | 'diff';

export function ReportAnalysis() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const navState = location.state as { from?: string; suiteName?: string; buildId?: string } | null;
  const { can, role, userName, userEmail } = useRole();
  const [data, setData] = React.useState<any>(null);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(false);
  const [isExecuting, setIsExecuting] = React.useState(false);
  const [insight, setInsight] = React.useState('');
  const [actionError, setActionError] = React.useState<string | null>(null);
  const [summaryOpen, setSummaryOpen] = React.useState(true);
  const [historyOpen, setHistoryOpen] = React.useState(false);
  const [thumbView, setThumbView] = React.useState<ThumbView>('diff');
  const [mainView, setMainView] = React.useState<ThumbView | 'compare'>('compare');
  const [viewMode, setViewMode] = React.useState<ComparisonViewMode>('overlay');
  const [showDiffOverlay, setShowDiffOverlay] = React.useState(true);
  const [zoom, setZoom] = React.useState<ZoomLevel>('fit');
  const [allRuns, setAllRuns] = React.useState<any[]>([]);
  const [isDrawing, setIsDrawing] = React.useState(false);
  const [localIgnoreRegions, setLocalIgnoreRegions] = React.useState<{ x: number; y: number; width: number; height: number }[]>([]);
  const imageRef = React.useRef<HTMLImageElement>(null);
  // All drag tracking in refs — avoids React closure/stale-state issues entirely
  const isDrawingRef = React.useRef(false);
  const dragStartRef = React.useRef<{ x: number; y: number } | null>(null);
  const dragRectRef = React.useRef<{ x: number; y: number; width: number; height: number } | null>(null);
  const previewDivRef = React.useRef<HTMLDivElement>(null); // live preview overlay div
  const localRegionsRef = React.useRef<{ x: number; y: number; width: number; height: number }[]>([]);
  const saveIgnoreRegionsRef = React.useRef<((r: typeof localIgnoreRegions) => void) | null>(null);
  React.useEffect(() => { isDrawingRef.current = isDrawing; }, [isDrawing]);
  React.useEffect(() => { localRegionsRef.current = localIgnoreRegions; }, [localIgnoreRegions]);
  const [imageVersion, setImageVersion] = React.useState(0);
  const [windowSize, setWindowSize] = React.useState({ w: window.innerWidth, h: window.innerHeight });

  React.useEffect(() => {
    const handleResize = () => {
      setWindowSize({ w: window.innerWidth, h: window.innerHeight });
    };
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Comments state and callbacks
  const [comments, setComments] = React.useState<any[]>([]);
  const [isCommenting, setIsCommenting] = React.useState(false);
  const [pendingComment, setPendingComment] = React.useState<{ x_pct: number; y_pct: number } | null>(null);
  const [newCommentText, setNewCommentText] = React.useState('');
  const [activeCommentId, setActiveCommentId] = React.useState<string | null>(null);

  const [commentsError, setCommentsError] = React.useState<string | null>(null);

  const fetchComments = React.useCallback(async () => {
    if (!id) return;
    setCommentsError(null);
    try {
      const payload = await api.get<{ ok: boolean; comments?: any[] }>(`/api/comments?run_id=${id}`);
      if (payload.ok) {
        setComments(payload.comments || []);
      }
    } catch (err) {
      console.error("Failed to fetch comments", err);
      setCommentsError("Could not load comments.");
    }
  }, [id]);

  React.useEffect(() => {
    fetchComments();
  }, [id, fetchComments]);

  useSSE('/api/events/stream', {
    onEvent: React.useCallback((event: any) => {
      if (event.type === 'comment_updated' && event.data && event.data.run_id === id) {
        fetchComments();
      }
    }, [id, fetchComments])
  });

  const submitComment = async () => {
    if (!id || !pendingComment || !newCommentText.trim()) return;
    try {
      const payload = await api.post<{ ok: boolean; error?: string }>('/api/comments/create', {
        run_id: id,
        x_pct: pendingComment.x_pct,
        y_pct: pendingComment.y_pct,
        content: newCommentText.trim()
      });
      if (payload.ok) {
        setPendingComment(null);
        setNewCommentText('');
        fetchComments();
      } else {
        setActionError(payload.error || 'Failed to post comment');
      }
    } catch {
      setActionError('Network error. Please try again.');
    }
  };

  const deleteComment = async (commentId: string) => {
    try {
      const payload = await api.post<{ ok: boolean; error?: string }>('/api/comments/delete', {
        comment_id: commentId
      });
      if (payload.ok) {
        if (activeCommentId === commentId) {
          setActiveCommentId(null);
        }
        fetchComments();
      } else {
        setActionError(payload.error || 'Failed to delete comment');
      }
    } catch {
      setActionError('Network failure — please try again.');
    }
  };

  // AI suggestions state and callbacks
  const [aiSuggestions, setAiSuggestions] = React.useState<any[]>([]);
  const [skippedRegions, setSkippedRegions] = React.useState<any[]>([]);
  const [selectedSuggestions, setSelectedSuggestions] = React.useState<number[]>([]);

  const fetchSuggestions = React.useCallback(async () => {
    if (!data?.baseline_name || !id) return;
    try {
      const payload = await api.get<{ ok: boolean; suggestions?: any[]; skipped?: any[] }>(`/api/ai-suggestions?baseline_name=${data.baseline_name}&run_id=${id}`);
      if (payload.ok) {
        setAiSuggestions(payload.suggestions || []);
        setSkippedRegions(payload.skipped || []);
        setSelectedSuggestions([]);
      }
    } catch (err) {
      console.error("Failed to fetch suggestions", err);
    }
  }, [data?.baseline_name, id]);

  React.useEffect(() => {
    if (data) {
      fetchSuggestions();
    }
  }, [data, fetchSuggestions]);

  const toggleSuggestion = (idx: number) => {
    setSelectedSuggestions(prev => prev.includes(idx) ? prev.filter(i => i !== idx) : [...prev, idx]);
  };

  // Applies only what the reviewer ticked. An ignore region silences that area
  // for every future run of this baseline, so nothing gets masked without
  // someone having looked at the box it covers.
  const applyAiSuggestions = () => {
    const chosen = selectedSuggestions.map(i => aiSuggestions[i]).filter(Boolean);
    if (chosen.length === 0) return;

    const merged = [...localIgnoreRegions];
    chosen.forEach(s => {
      const f = { x: s.x, y: s.y, width: s.width, height: s.height };
      const exists = merged.some(m => m.x === f.x && m.y === f.y && m.width === f.width && m.height === f.height);
      if (!exists) {
        merged.push(f);
      }
    });

    setLocalIgnoreRegions(merged);
    saveIgnoreRegionsOnBackend(merged);
    setAiSuggestions(prev => prev.filter((_, i) => !selectedSuggestions.includes(i)));
    setSelectedSuggestions([]);
  };

  // Pins only exist in the overlay view, so reaching a comment from anywhere
  // else means switching there first, then scrolling the pin into the pane —
  // an image zoomed past the viewport can leave a pin well off screen.
  const jumpToFirstComment = React.useCallback(() => {
    const first = comments[0];
    if (!first) return;
    setViewMode('overlay');
    setMainView('compare');
    setActiveCommentId(first.id);
    requestAnimationFrame(() => {
      document
        .querySelector(`[data-comment-pin="${first.id}"]`)
        ?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
    });
  }, [comments]);

  const handleImageClickForComment = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const x_pct = (x / rect.width) * 100;
    const y_pct = (y / rect.height) * 100;
    setPendingComment({ x_pct, y_pct });
  };

  const fetchData = React.useCallback((silent = false) => {
    if (!id) return;
    if (!silent) {
      setLoading(true);
    }
    setLoadError(false);
    api.get<any>(`/api/run?id=${id}`)
      .then(run => {
        setData(run);
        setInsight(run.ai_explanation || 'No automated summary for this run.');
        setImageVersion(v => v + 1);
        setLoading(false);
      })
      .catch(() => { setLoadError(true); setLoading(false); });
  }, [id]);

  React.useEffect(() => {
    // Only sync from backend data when NOT in drawing mode
    // (avoids overwriting locally-drawn regions before they are confirmed by the backend)
    if (data && !isDrawing) {
      const parsed = (data.ignore_regions ?? []).map((r: any) => {
        if (Array.isArray(r)) {
          return { x: r[0], y: r[1], width: r[2], height: r[3] };
        }
        return r;
      });
      setLocalIgnoreRegions(parsed);
    }
  }, [data, isDrawing]);


  const saveIgnoreRegionsOnBackend = React.useCallback(async (regions: typeof localIgnoreRegions) => {
    try {
      await api.post<any>('/api/ignore-regions', {
        name: data?.baseline_name,
        run_id: id,
        ignore_regions: regions
      });
      clearApiCacheEntry('/api/dashboard');
      fetchData(true);
    } catch (err) {
      console.error("Failed to save ignore regions", err);
    }
  }, [data, id, fetchData]);

  // Keep a ref to saveIgnoreRegionsOnBackend so it's always fresh inside event listeners
  React.useEffect(() => { saveIgnoreRegionsRef.current = saveIgnoreRegionsOnBackend; }, [saveIgnoreRegionsOnBackend]);

  const deleteIgnoreRegion = (index: number) => {
    const updated = localIgnoreRegions.filter((_, i) => i !== index);
    setLocalIgnoreRegions(updated);
    saveIgnoreRegionsOnBackend(updated);
  };

  // Update the live preview div directly via DOM — no React re-render needed during drag
  const updatePreviewDiv = (r: { x: number; y: number; width: number; height: number } | null) => {
    const el = previewDivRef.current;
    if (!el) return;
    if (!r) {
      el.style.display = 'none';
      return;
    }
    el.style.display = 'block';
    el.style.left = `${r.x}px`;
    el.style.top = `${r.y}px`;
    el.style.width = `${r.width}px`;
    el.style.height = `${r.height}px`;
  };

  const handleCanvasMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDrawingRef.current || !imageRef.current) return;
    e.preventDefault();
    const rect = imageRef.current.getBoundingClientRect();
    const start = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    dragStartRef.current = start;
    dragRectRef.current = { x: start.x, y: start.y, width: 0, height: 0 };
    updatePreviewDiv(dragRectRef.current);
  };

  const handleCanvasMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDrawingRef.current || !dragStartRef.current || !imageRef.current) return;
    const rect = imageRef.current.getBoundingClientRect();
    const curX = e.clientX - rect.left;
    const curY = e.clientY - rect.top;
    const start = dragStartRef.current;
    const r = {
      x: Math.min(start.x, curX),
      y: Math.min(start.y, curY),
      width: Math.abs(start.x - curX),
      height: Math.abs(start.y - curY),
    };
    dragRectRef.current = r;
    updatePreviewDiv(r);
  };

  // Global mouseup registered once; reads fresh values from refs only
  React.useEffect(() => {
    const onGlobalMouseUp = () => {
      if (!isDrawingRef.current || !dragStartRef.current) return;
      const r = dragRectRef.current;
      const img = imageRef.current;
      dragStartRef.current = null;
      dragRectRef.current = null;
      updatePreviewDiv(null);
      if (!r || !img) return;
      const displayRect = img.getBoundingClientRect();
      if (displayRect.width === 0 || displayRect.height === 0) return;
      const scaleX = img.naturalWidth / displayRect.width;
      const scaleY = img.naturalHeight / displayRect.height;
      const newRegion = {
        x: Math.round(r.x * scaleX),
        y: Math.round(r.y * scaleY),
        width: Math.round(r.width * scaleX),
        height: Math.round(r.height * scaleY),
      };
      if (newRegion.width > 3 && newRegion.height > 3) {
        const updated = [...localRegionsRef.current, newRegion];
        setLocalIgnoreRegions(updated);
        if (saveIgnoreRegionsRef.current) saveIgnoreRegionsRef.current(updated);
      }
    };
    window.addEventListener('mouseup', onGlobalMouseUp);
    return () => window.removeEventListener('mouseup', onGlobalMouseUp);
  }, []);

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
                aria-label="Delete ignore region"
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
        {/* Live drag preview — updated via direct DOM, NOT React state */}
        <div
          ref={previewDivRef}
          className="absolute border-2 border-dashed border-red-400 bg-red-400/10 pointer-events-none"
          style={{ display: 'none', left: 0, top: 0, width: 0, height: 0 }}
        />
      </div>
    );
  };

  React.useEffect(() => {
    api.get<any>('/api/dashboard')
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

  const buildRuns = React.useMemo(() => {
    if (!data || !data.build_id) return [];
    return allRuns.filter((r: any) => r.build_id === data.build_id);
  }, [allRuns, data]);

  const buildReviewStats = React.useMemo(() => {
    if (buildRuns.length === 0) return { reviewed: 0, total: 0 };
    const total = buildRuns.length;
    const unreviewed = buildRuns.filter((r: any) => {
      const rs = normalizeReviewStatus(r.review_status ?? r.status);
      return rs === 'unreviewed';
    }).length;
    return { reviewed: total - unreviewed, total };
  }, [buildRuns]);

  const uniqueBrowsers = React.useMemo(() => {
    return Array.from(new Set(relatedRuns.map((r: any) => r.browser).filter(Boolean)));
  }, [relatedRuns]);

  const submitReview = React.useCallback(async (decision: 'approved' | 'rejected') => {
    if (!id) return;
    setIsExecuting(true);
    try {
      const result = await api.post<{ ok: boolean; error?: string }>('/api/actions/review', {
        run: id,
        decision,
        reviewer: userName || userEmail || role
      });
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
  }, [id, userName, userEmail, role, fetchData]);

  React.useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return;

      if (e.key === 'd') {
        setShowDiffOverlay(prev => !prev);
      } else if (e.key === 'i') {
        if (can('manage_baselines')) setIsDrawing(prev => !prev);
      } else if (e.key === 'a') {
        if (can('approve')) submitReview('approved');
      } else if (e.key === 'r') {
        if (can('approve')) submitReview('rejected');
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
  }, [data, allRuns, id, submitReview, navigate, navState, can]);

  React.useEffect(() => { fetchData(); }, [id, fetchData]);

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
  const history = (data.decision_history || []).filter((h: any) => h.status === 'approved' || h.status === 'rejected');
  const isCompactDevice = /iphone|pixel|android|mobile/i.test(String(data.capture?.device || '').toLowerCase());
  const aspectRatio = isCompactDevice ? '9/16' : '16/10';
  const hasBinaryDiff = Number(result.diff_pixels || 0) > 0;
  const mismatchRaw = Number(result.mismatch_pct ?? result.diff_percent ?? data.mismatch ?? 0);
  const diffPct = `${mismatchRaw.toFixed(2)}%`;
  const isPass = status === 'PASS';
  const isFailed = status === 'FAIL' || status === 'FAILED';

  const baselineUrl = `/baseline/${data.baseline_name}/baseline.webp`;
  const currentUrl = `/artifacts/${id}/current.webp`;
  const diffUrl = `/artifacts/${id}/diff_overlay.webp?v=${imageVersion}`;


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
            ) : navState?.from === 'build' && navState.buildId ? (
              <Link to={`/build/${navState.buildId}`} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline">← Back to build</Link>
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
              {data.ai_assessment?.low_confidence && (
                <span className="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/20 text-amber-600 dark:text-amber-400">
                  ⚠️ Low Confidence
                </span>
              )}

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
                disabled={!can('manage_baselines')}
              >
                {isDrawing ? "Save & Finish" : "✏️ Draw Ignore Regions"}
              </Button>
              {aiSuggestions.length > 0 && can('manage_baselines') && (
                <div className="p-3 bg-indigo-50 dark:bg-indigo-950/20 border border-indigo-100 dark:border-indigo-900/30 rounded-lg space-y-2">
                  <p className="text-[10px] font-bold text-indigo-700 dark:text-indigo-400 flex items-center gap-1">
                    ✨ Dynamic content detected ({aiSuggestions.length})
                  </p>
                  <p className="text-[10px] text-indigo-600 dark:text-indigo-500 leading-normal font-normal">
                    These areas changed in nearly every recent run <em>and</em> showed different content each time — ads, clocks, carousels. Tick the ones to mask.
                  </p>
                  <ul className="space-y-1.5">
                    {aiSuggestions.map((s, idx) => (
                      <li key={idx}>
                        <label className="flex gap-2 items-start cursor-pointer bg-white/70 dark:bg-zinc-900/40 rounded px-2 py-1.5">
                          <input
                            type="checkbox"
                            className="mt-0.5 accent-indigo-600 cursor-pointer"
                            checked={selectedSuggestions.includes(idx)}
                            onChange={() => toggleSuggestion(idx)}
                          />
                          <span className="min-w-0">
                            <span className="block text-[10px] font-mono text-[var(--on-surface)]">
                              [{s.x}, {s.y}] · {s.width}×{s.height}px
                            </span>
                            <span className="block text-[10px] text-indigo-600 dark:text-indigo-500 font-normal leading-normal">
                              Changed in {s.frequency}/{s.total_runs_analyzed} runs, different content each time
                              {typeof s.variability === 'number' && ` (variability ${(s.variability * 100).toFixed(1)}%)`}
                            </span>
                          </span>
                        </label>
                      </li>
                    ))}
                  </ul>
                  <button
                    onClick={applyAiSuggestions}
                    disabled={selectedSuggestions.length === 0}
                    className="w-full py-1 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed text-white rounded text-[10px] font-bold cursor-pointer transition-colors"
                  >
                    Apply {selectedSuggestions.length > 0 ? `${selectedSuggestions.length} selected` : 'selected'} region{selectedSuggestions.length === 1 ? '' : 's'}
                  </button>
                </div>
              )}
              {skippedRegions.length > 0 && can('manage_baselines') && (
                <div className="p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-100 dark:border-amber-900/30 rounded-lg space-y-1.5">
                  <p className="text-[10px] font-bold text-amber-700 dark:text-amber-400">
                    ⚠ Repeats, but not masked ({skippedRegions.length})
                  </p>
                  {skippedRegions.map((s, idx) => (
                    <p key={idx} className="text-[10px] text-amber-700 dark:text-amber-500 font-normal leading-normal">
                      <span className="font-mono">[{s.x}, {s.y}] · {s.width}×{s.height}px</span> — {s.detail}
                    </p>
                  ))}
                </div>
              )}
              {localIgnoreRegions.length > 0 ? (
                <ul className="space-y-1.5 max-h-32 overflow-y-auto">
                  {localIgnoreRegions.map((rect, idx) => (
                    <li key={idx} className="text-xs font-mono text-[var(--on-surface-variant)] flex items-center justify-between bg-stone-50 dark:bg-zinc-800 px-2 py-1 rounded">
                      <span>[{rect.x}, {rect.y}] · {rect.width}×{rect.height}px</span>
                      {can('manage_baselines') && (
                        <button
                          onClick={() => deleteIgnoreRegion(idx)}
                          className="text-red-500 hover:text-red-700 font-bold ml-2 cursor-pointer"
                          title="Remove region"
                        >
                          ×
                        </button>
                      )}
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
          <Panel title="Changed regions">
            {regions.length > 0 ? (
              <ul className="space-y-2 max-h-48 overflow-y-auto">
                {(() => {
                  const getRegionPriorityInfo = (r: any) => {
                    const area = r.area || (r.width * r.height) || 0;
                    const meanDelta = r.mean_delta || 0;
                    const score = area * meanDelta;
                    
                    let priorityLabel = 'Low';
                    let badgeColor = 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/30 dark:text-sky-300 dark:border-sky-800';
                    
                    if (score > 40000 || meanDelta > 120 || area > 80000) {
                      priorityLabel = 'Critical';
                      badgeColor = 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/30 dark:text-rose-300 dark:border-rose-800';
                    } else if (score > 4000 || meanDelta > 30 || area > 10000) {
                      priorityLabel = 'Warning';
                      badgeColor = 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/30 dark:text-amber-300 dark:border-amber-800';
                    }
                    return { score, label: priorityLabel, badgeColor };
                  };

                  const sortedRegions = [...regions].map((r: any) => {
                    const info = getRegionPriorityInfo(r);
                    return { ...r, ...info };
                  }).sort((a: any, b: any) => b.score - a.score);

                  return sortedRegions.map((r: any, idx: number) => (
                    <li key={idx} className="text-xs p-2 rounded-md bg-stone-50 dark:bg-zinc-800/50 border border-[var(--outline)]">
                      <div className="flex items-center justify-between gap-2 flex-wrap">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium">{r.label || `Region ${idx + 1}`}</span>
                          {r.change_type && <ChangeTypeBadge label={r.change_type} />}
                        </div>
                        <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold border ${r.badgeColor}`}>
                          {r.label}
                        </span>
                      </div>
                      <p className="text-[var(--on-surface-variant)] mt-0.5">[{r.x}, {r.y}] · {r.width}×{r.height}px</p>
                    </li>
                  ));
                })()}
              </ul>
            ) : (
              <p className="text-xs text-[var(--on-surface-variant)]">No regions detected</p>
            )}
          </Panel>
          <Panel title="Collaborative Comments">
            <div className="space-y-3">
              {comments.length > 0 ? (
                <ul className="space-y-2.5 max-h-48 overflow-y-auto">
                  {comments.map((c: any) => (
                    <li key={c.id} className="text-xs p-2 rounded-md bg-stone-50 dark:bg-zinc-800/50 border border-[var(--outline)] relative group">
                      <div className="flex justify-between items-center gap-2 mb-0.5">
                        <span className="font-semibold text-indigo-600 dark:text-indigo-400 text-[10px] truncate">{c.author}</span>
                        <span className="text-[9px] text-stone-400">{new Date(c.created_at * 1000).toLocaleTimeString()}</span>
                      </div>
                      <p className="text-[var(--on-surface)] break-words whitespace-pre-wrap">{c.content}</p>
                      <div className="flex items-center justify-between gap-2 mt-1.5">
                        <button
                          onClick={() => {
                            setViewMode('overlay');
                            setMainView('compare');
                            setActiveCommentId(c.id);
                          }}
                          className="text-[9px] text-indigo-500 hover:underline cursor-pointer"
                        >
                          Show on Image
                        </button>
                        {(role === 'admin' || c.author === userEmail) && (
                          <button
                            onClick={() => deleteComment(c.id)}
                            className="text-[9px] text-red-500 hover:text-red-700 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer font-medium"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-[var(--on-surface-variant)] leading-relaxed">
                  No comments yet. Switch to Overlay view mode to drop comment pins directly over layout differences.
                </p>
              )}
            </div>
          </Panel>
          <Panel title="Export Report">
            <div className="space-y-2">
              <a
                href={`/artifacts/${id}/report.html`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center justify-center gap-1.5 w-full py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded text-xs font-bold transition-colors cursor-pointer text-center no-underline"
              >
                📄 Open HTML Report
              </a>
              <p className="text-[10px] text-[var(--on-surface-variant)] text-center leading-normal">
                Open a standalone interactive report page that you can save or print to PDF.
              </p>
            </div>
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

          <div className="pt-4 border-t border-[var(--outline)] space-y-2">
            <h4 className="text-[10px] font-bold text-[var(--on-surface-variant)] uppercase tracking-wider px-1">Keyboard Shortcuts</h4>
            <div className="grid grid-cols-2 gap-y-2.5 gap-x-3 text-[11px] p-2 bg-stone-50 dark:bg-zinc-900 rounded-md border border-slate-100 dark:border-slate-800">
              <div className="flex items-center gap-1.5"><kbd className="px-1.5 py-0.5 font-bold bg-white dark:bg-zinc-800 border border-slate-200 dark:border-slate-700 rounded text-[9px] shadow-sm">i</kbd> <span className="text-[var(--on-surface-variant)] font-medium">Draw Mode</span></div>
              <div className="flex items-center gap-1.5"><kbd className="px-1.5 py-0.5 font-bold bg-white dark:bg-zinc-800 border border-slate-200 dark:border-slate-700 rounded text-[9px] shadow-sm">d</kbd> <span className="text-[var(--on-surface-variant)] font-medium">Toggle Diff</span></div>
              <div className="flex items-center gap-1.5"><kbd className="px-1.5 py-0.5 font-bold bg-white dark:bg-zinc-800 border border-slate-200 dark:border-slate-700 rounded text-[9px] shadow-sm">Space</kbd> <span className="text-[var(--on-surface-variant)] font-medium">Flip View</span></div>
              <div className="flex items-center gap-1.5"><kbd className="px-1.5 py-0.5 font-bold bg-white dark:bg-zinc-800 border border-slate-200 dark:border-slate-700 rounded text-[9px] shadow-sm">a</kbd> <span className="text-[var(--on-surface-variant)] font-medium">Approve</span></div>
              <div className="flex items-center gap-1.5"><kbd className="px-1.5 py-0.5 font-bold bg-white dark:bg-zinc-800 border border-slate-200 dark:border-slate-700 rounded text-[9px] shadow-sm">r</kbd> <span className="text-[var(--on-surface-variant)] font-medium">Reject</span></div>
              <div className="flex items-center gap-1.5"><kbd className="px-1.5 py-0.5 font-bold bg-white dark:bg-zinc-800 border border-slate-200 dark:border-slate-700 rounded text-[9px] shadow-sm">←/→</kbd> <span className="text-[var(--on-surface-variant)] font-medium">Prev/Next</span></div>
            </div>
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
            <p className="text-xs text-[var(--on-surface-variant)] flex items-center gap-2 flex-wrap">
              <span>Severity: {severity}{!isPass && ` · ${diffPct} diff`}</span>
              {buildReviewStats.total > 0 && (
                <>
                  <span className="text-slate-350 dark:text-slate-700 font-normal">|</span>
                  <span className="font-semibold text-emerald-600 dark:text-emerald-450">Reviewed: {buildReviewStats.reviewed} / {buildReviewStats.total}</span>
                </>
              )}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => window.open(`/api/runs/${id}/export`, '_blank')}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-stone-100 dark:bg-zinc-800 text-[var(--on-surface-variant)] hover:bg-stone-200 dark:hover:bg-zinc-700 border border-[var(--outline)] transition-colors"
              title="Export as shareable HTML file"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export
            </button>
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
        
        {/* Device is chosen when the capture is configured (Actions / Baselines),
            so a viewport switcher here only duplicated it. */}
        {relatedRuns.length > 1 && uniqueBrowsers.length > 1 && (
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
            commentCount={comments.length}
            onJumpToComments={jumpToFirstComment}
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
              <div className="flex-1 min-h-0 relative flex items-center justify-center p-4 bg-stone-100 dark:bg-zinc-900/50 overflow-auto">
                <div 
                  className="relative inline-block max-w-full select-none cursor-crosshair"
                  onMouseDown={handleCanvasMouseDown}
                  onMouseMove={handleCanvasMouseMove}
                >
                  <img
                    ref={imageRef}
                    src={baselineUrl}
                    alt="Baseline Drawing Canvas"
                    className="max-h-[calc(100vh-16rem)] max-w-full block select-none pointer-events-none"
                    onLoad={() => {
                      // Trigger state refresh for alignment
                      setLocalIgnoreRegions(prev => [...prev]);
                    }}
                    draggable={false}
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
            <div
              className="flex-1 min-h-0 panel overflow-hidden flex flex-col cursor-pointer select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-inset"
              onClick={() => setMainView('current')}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); setMainView('current'); } }}
              role="button"
              tabIndex={0}
              aria-label="Baseline image. Click or press Enter to flip to current."
            >
              <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-medium flex justify-between items-center bg-stone-50 dark:bg-zinc-900">
                <span>Baseline (Click to flash toggle)</span>
                <span className="text-[10px] text-indigo-500 font-mono">SPACE to toggle</span>
              </div>
              <div className="flex-1 min-h-0 relative"><div className="absolute inset-0"><ImageFrame src={baselineUrl} alt="Baseline" fill className="h-full w-full" /></div></div>
            </div>
          ) : mainView === 'current' ? (
            <div
              className="flex-1 min-h-0 panel overflow-hidden flex flex-col cursor-pointer select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 focus-visible:ring-inset"
              onClick={() => setMainView('baseline')}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); setMainView('baseline'); } }}
              role="button"
              tabIndex={0}
              aria-label="Changes image. Click or press Enter to flip to baseline."
            >
              <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-medium flex justify-between items-center bg-stone-50 dark:bg-zinc-900">
                <span>Changes (Click to flash toggle)</span>
                <span className="text-[10px] text-indigo-500 font-mono">SPACE to toggle</span>
              </div>
              <div className="flex-1 min-h-0 relative"><div className="absolute inset-0"><DiffHighlightFrame currentUrl={currentUrl} diffOverlayUrl={diffUrl} showDiff={showDiffOverlay} zoom={zoom === 'fit' ? 1 : zoom} fill className="h-full w-full" alt="Changes" /></div></div>
            </div>
          ) : viewMode === 'overlay' ? (
            <div 
              className="flex-1 min-h-0 panel overflow-hidden flex flex-col select-none" 
            >
              <div className="px-3 py-2 border-b border-[var(--outline)] text-xs font-semibold flex justify-between items-center bg-stone-50 dark:bg-zinc-900 shrink-0">
                <span className="text-[var(--on-surface)]">
                  {showDiffOverlay ? 'Diff Highlight Overlay' : 'Current Snapshot'}
                </span>
                <div className="flex items-center gap-3">
                  <Button
                    variant={isCommenting ? "approve" : "secondary"}
                    size="sm"
                    className="text-[10px] px-2 py-0.5"
                    onClick={() => { setIsCommenting(!isCommenting); setPendingComment(null); }}
                  >
                    {isCommenting ? "💬 Close Comments" : "💬 Add Comments"}
                  </Button>
                  <span className="text-[10px] text-indigo-500 font-mono">D to toggle diff · Click image to {isCommenting ? "drop comment pin" : "toggle diff"}</span>
                </div>
              </div>
              <div className="flex-1 min-h-0 relative flex p-4 bg-stone-100 dark:bg-zinc-900/50 overflow-auto">
                {/* m-auto rather than justify-center: auto margins collapse to 0 once the
                    zoomed image overflows, so its top-left stays scrollable. The wrapper
                    takes its size from the image alone — comment pins are positioned in
                    percentages of this box. */}
                <div
                  className={cn(
                    "relative m-auto shrink-0",
                    // Bounded by the pane while fitting; uncapped once zoomed in, so the
                    // enlarged image is not squeezed back to the pane width.
                    zoom === 'fit' || zoom === 1 ? "max-w-full" : "max-w-none",
                    isCommenting ? "cursor-chat" : "cursor-pointer",
                  )}
                  onClick={(e) => {
                    if (isCommenting) {
                      handleImageClickForComment(e);
                    } else {
                      setShowDiffOverlay(!showDiffOverlay);
                    }
                  }}
                >
                  <DiffHighlightFrame 
                    currentUrl={currentUrl} 
                    diffOverlayUrl={diffUrl} 
                    showDiff={showDiffOverlay} 
                    zoom={zoom === 'fit' ? 1 : zoom} 
                    fill={false} 
                    className="max-h-[calc(100vh-16rem)] max-w-full block" 
                    alt="Current Screenshot" 
                  />
                  {/* Render Comments Pins */}
                  {comments.map((c: any) => (
                    <div
                      key={c.id}
                      data-comment-pin={c.id}
                      className={cn(
                        "absolute w-6 h-6 bg-indigo-600 border-2 border-white text-white rounded-full flex items-center justify-center text-[10px] font-bold shadow-lg transform -translate-x-1/2 -translate-y-1/2 cursor-pointer hover:scale-110 hover:bg-indigo-700 transition-all z-20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white",
                        activeCommentId === c.id && "ring-2 ring-indigo-400 ring-offset-2 scale-110",
                      )}
                      style={{ left: `${c.x_pct}%`, top: `${c.y_pct}%` }}
                      title={`${c.author}: ${c.content}`}
                      onClick={(e) => {
                        e.stopPropagation();
                        setActiveCommentId(activeCommentId === c.id ? null : c.id);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          e.stopPropagation();
                          setActiveCommentId(activeCommentId === c.id ? null : c.id);
                        }
                      }}
                      role="button"
                      tabIndex={0}
                      aria-label={`Comment by ${c.author}: ${c.content}`}
                    >
                      📍
                      {activeCommentId === c.id && (
                        <div 
                          className="absolute left-7 top-0 w-56 p-3 bg-white dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 rounded-lg shadow-xl z-30 text-xs text-left cursor-default select-text"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <p className="font-semibold text-[10px] text-indigo-600 dark:text-indigo-400 mb-0.5 truncate">{c.author}</p>
                          <p className="text-[var(--on-surface)] break-words whitespace-pre-wrap leading-normal font-normal">{c.content}</p>
                          <p className="text-[9px] text-stone-400 mt-1.5">{new Date(c.created_at * 1000).toLocaleString()}</p>
                          {(role === 'admin' || c.author === userEmail) && (
                            <button
                              onClick={() => deleteComment(c.id)}
                              className="text-[9px] text-red-500 hover:text-red-700 font-bold mt-2 cursor-pointer block"
                            >
                              Delete
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  ))}

                  {/* Render Pending Comment Input */}
                  {pendingComment && (
                    <div 
                      className="absolute p-3 bg-white dark:bg-zinc-800 border border-slate-200 dark:border-zinc-700 rounded-lg shadow-xl z-30 text-xs w-64 transform -translate-x-1/2 mt-3 cursor-default"
                      style={{ left: `${pendingComment.x_pct}%`, top: `${pendingComment.y_pct}%` }}
                      onClick={(e) => e.stopPropagation()}
                    >
                      <p className="font-bold text-[10px] text-[var(--on-surface-variant)] uppercase tracking-wider mb-2">New Comment Pin</p>
                      <textarea
                        value={newCommentText}
                        onChange={(e) => setNewCommentText(e.target.value)}
                        placeholder="Write a comment..."
                        rows={3}
                        className="w-full p-2 border border-[var(--outline)] bg-[var(--surface)] rounded-md text-xs resize-none outline-none focus:ring-2 focus:ring-indigo-500/20 text-[var(--on-surface)]"
                        autoFocus
                      />
                      <div className="flex justify-end gap-2 mt-2">
                        <button onClick={() => setPendingComment(null)} className="px-2.5 py-1.5 border border-[var(--outline)] rounded-md font-bold text-[10px] text-slate-500 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer">Cancel</button>
                        <button onClick={submitComment} className="px-2.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-md font-bold text-[10px] cursor-pointer">Post</button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
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
