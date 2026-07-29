import React from 'react';
import { Columns2, GitCompare, Layers, ZoomIn, ZoomOut, Maximize2, Eye } from 'lucide-react';
import { cn } from '../../lib/utils';

export type ComparisonViewMode = 'side-by-side' | 'slider' | 'overlay';
export type ZoomLevel = 'fit' | 1 | 1.25 | 1.5 | 2;

const ZOOM_STEPS: ZoomLevel[] = ['fit', 1, 1.25, 1.5, 2];

export function ComparisonToolbar({ viewMode, onViewModeChange, showDiff, onShowDiffChange, hasDiff = true, zoom, onZoomChange }: {
  viewMode: ComparisonViewMode;
  onViewModeChange: (mode: ComparisonViewMode) => void;
  showDiff: boolean;
  onShowDiffChange: (show: boolean) => void;
  hasDiff?: boolean;
  zoom: ZoomLevel;
  onZoomChange: (zoom: ZoomLevel) => void;
}) {
  const idx = ZOOM_STEPS.indexOf(zoom);
  const zoomOut = () => onZoomChange(ZOOM_STEPS[Math.max(0, idx - 1)]);
  const zoomIn = () => onZoomChange(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, idx + 1)]);
  const zoomLabel = zoom === 'fit' ? 'Fit' : `${Math.round(Number(zoom) * 100)}%`;

  return (
    <div className="shrink-0 flex items-center gap-1 px-3 py-2 border-b border-[var(--outline)] bg-[var(--surface)] flex-wrap">
      <ToolbarButton active={viewMode === 'overlay'} onClick={() => onViewModeChange('overlay')} title="Single page overlay">
        <Eye className="w-4 h-4" /><span className="hidden sm:inline">Overlay</span>
      </ToolbarButton>
      <ToolbarButton active={viewMode === 'side-by-side'} onClick={() => onViewModeChange('side-by-side')} title="Side by side">
        <Columns2 className="w-4 h-4" /><span className="hidden sm:inline">Side by side</span>
      </ToolbarButton>
      <ToolbarButton active={viewMode === 'slider'} onClick={() => onViewModeChange('slider')} title="Slider compare">
        <Layers className="w-4 h-4" /><span className="hidden sm:inline">Slider</span>
      </ToolbarButton>
      <div className="w-px h-6 bg-[var(--outline)] mx-1" />
      <ToolbarButton active={showDiff} onClick={() => onShowDiffChange(!showDiff)} disabled={!hasDiff} title={showDiff ? 'Hide diff highlights' : 'Show diff highlights'}>
        <GitCompare className="w-4 h-4" /><span className="hidden sm:inline">{showDiff ? 'Hide diff' : 'Show diff'}</span>
      </ToolbarButton>
      <div className="w-px h-6 bg-[var(--outline)] mx-1" />
      <ToolbarButton onClick={zoomOut} disabled={idx <= 0} title="Zoom out"><ZoomOut className="w-4 h-4" /></ToolbarButton>
      <span className="text-xs font-medium text-[var(--on-surface-variant)] min-w-[3rem] text-center">{zoomLabel}</span>
      <ToolbarButton onClick={zoomIn} disabled={idx >= ZOOM_STEPS.length - 1} title="Zoom in"><ZoomIn className="w-4 h-4" /></ToolbarButton>
      <ToolbarButton active={zoom === 'fit'} onClick={() => onZoomChange('fit')} title="Fit to pane"><Maximize2 className="w-4 h-4" /></ToolbarButton>
    </div>
  );
}

function ToolbarButton({ active, onClick, disabled, title, children }: { active?: boolean; onClick: () => void; disabled?: boolean; title: string; children: React.ReactNode }) {
  return (
    <button type="button" title={title} disabled={disabled} onClick={onClick} className={cn(
      'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors',
      active ? 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950/50 dark:text-indigo-300' : 'text-[var(--on-surface-variant)] hover:bg-stone-100 dark:hover:bg-zinc-800',
      disabled && 'opacity-40 cursor-not-allowed'
    )}>{children}</button>
  );
}
