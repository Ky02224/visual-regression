import React, { useState, useRef, useEffect } from 'react';
import { cn } from '../lib/utils';
import { Maximize2 } from 'lucide-react';
import { DiffHighlightFrame } from './ui/DiffHighlightFrame';
import type { ZoomLevel } from './ui/ComparisonToolbar';

interface ComparisonSliderProps {
  baselineUrl: string;
  currentUrl: string;
  diffOverlayUrl?: string;
  showDiff?: boolean;
  zoom?: ZoomLevel;
  labelBaseline?: string;
  labelCurrent?: string;
  compact?: boolean;
}

function zoomScale(zoom: ZoomLevel = 'fit'): number {
  return zoom === 'fit' ? 1 : zoom;
}

export function ComparisonSlider({
  baselineUrl,
  currentUrl,
  diffOverlayUrl,
  showDiff = false,
  zoom = 'fit',
  labelBaseline = 'Baseline',
  labelCurrent = 'Current',
  compact = false,
}: ComparisonSliderProps) {
  const [sliderPosition, setSliderPosition] = useState(50);
  const [isDragging, setIsDragging] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const scale = zoomScale(zoom);

  const handleMove = (clientX: number) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(clientX - rect.left, rect.width));
    setSliderPosition((x / rect.width) * 100);
  };

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => { if (isDragging) handleMove(e.clientX); };
    const onTouchMove = (e: TouchEvent) => { if (isDragging) handleMove(e.touches[0].clientX); };
    const onUp = () => setIsDragging(false);
    if (isDragging) {
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onUp);
      window.addEventListener('touchmove', onTouchMove);
      window.addEventListener('touchend', onUp);
    }
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onUp);
    };
  }, [isDragging]);

  const renderSlider = (className: string) => (
    <div
      ref={containerRef}
      className={cn('relative bg-stone-100 dark:bg-zinc-900 overflow-hidden border border-[var(--outline)] select-none group cursor-col-resize', className)}
      onMouseDown={() => setIsDragging(true)}
      onTouchStart={() => setIsDragging(true)}
    >
      <div className="absolute inset-0" style={{ transform: `scale(${scale})`, transformOrigin: 'center center' }}>
        <DiffHighlightFrame currentUrl={currentUrl} diffOverlayUrl={diffOverlayUrl} showDiff={showDiff} fill className="h-full w-full" alt={labelCurrent} />
      </div>
      <div className="absolute inset-0 w-full h-full pointer-events-none" style={{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }}>
        <div className="absolute inset-0" style={{ transform: `scale(${scale})`, transformOrigin: 'center center' }}>
          <img src={baselineUrl} alt={labelBaseline} className="absolute inset-0 w-full h-full object-contain" referrerPolicy="no-referrer" />
        </div>
        <div className="absolute top-3 left-3 px-2 py-1 bg-black/50 rounded text-[10px] font-medium text-white">{labelBaseline}</div>
      </div>
      <div className="absolute top-3 right-3 px-2 py-1 bg-black/50 rounded text-[10px] font-medium text-white pointer-events-none" style={{ opacity: sliderPosition > 85 ? 0 : 1 }}>{labelCurrent}</div>
      <div className="absolute inset-y-0 z-10 w-0.5 bg-white shadow-md flex items-center justify-center" style={{ left: `${sliderPosition}%` }}>
        <div className="w-7 h-7 bg-white rounded-full shadow border-2 border-stone-200 dark:border-zinc-700 flex items-center justify-center -ml-0.5">
          <div className="flex gap-0.5"><div className="w-0.5 h-3 bg-stone-300 rounded-full" /><div className="w-0.5 h-3 bg-stone-300 rounded-full" /></div>
        </div>
      </div>
      {!compact && (
        <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(true); }} className="absolute bottom-3 right-3 p-1.5 bg-black/40 hover:bg-black/55 text-white rounded-md z-20" aria-label="Expand">
          <Maximize2 className="w-4 h-4" />
        </button>
      )}
    </div>
  );

  return (
    <>
      {renderSlider(compact ? 'mx-auto w-full max-w-[360px] h-[680px] rounded-md' : 'w-full h-full min-h-[480px] rounded-md')}
      {expanded && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
          <div className="absolute inset-0 bg-black/60" onClick={() => setExpanded(false)} />
          <div className="relative w-full max-w-6xl h-[85vh] rounded-md overflow-hidden border border-[var(--outline)] bg-[var(--surface)] shadow-xl">
            <button type="button" onClick={() => setExpanded(false)} className="absolute top-3 right-3 z-20 px-3 py-1.5 rounded-md bg-black/50 hover:bg-black/65 text-white text-xs">Close</button>
            {renderSlider('absolute inset-0 rounded-none border-0')}
          </div>
        </div>
      )}
    </>
  );
}
