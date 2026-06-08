import React from 'react';
import { cn } from '../lib/utils';
import { DiffHighlightFrame } from './ui/DiffHighlightFrame';
import { ComparisonImageView } from './ui/ComparisonImageView';
import type { ZoomLevel } from './ui/ComparisonToolbar';

function zoomScale(zoom: ZoomLevel): number {
  return zoom === 'fit' ? 1 : zoom;
}

function ComparisonPane({ label, sublabel, children }: { label: string; sublabel?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-0 min-w-0 flex-1 h-full">
      <div className="px-3 py-2 border-b border-[var(--outline)] bg-[var(--surface)] shrink-0">
        <p className="text-xs font-medium text-[var(--on-surface)]">{label}</p>
        {sublabel && <p className="text-[11px] text-[var(--on-surface-variant)] truncate">{sublabel}</p>}
      </div>
      <div className="flex-1 min-h-0 min-w-0 relative bg-stone-50 dark:bg-zinc-900 overflow-hidden">{children}</div>
    </div>
  );
}

export function SideBySideComparison({ baselineUrl, currentUrl, diffOverlayUrl, showDiffOverlay = false, zoom = 'fit', labelBaseline = 'Baseline', labelCurrent = 'Changes', className }: {
  baselineUrl: string; currentUrl: string; diffOverlayUrl?: string; showDiffOverlay?: boolean; zoom?: ZoomLevel; labelBaseline?: string; labelCurrent?: string; className?: string;
}) {
  const scale = zoomScale(zoom);
  const changesSublabel = showDiffOverlay ? 'Diff highlights on (background dimmed)' : 'Current snapshot';
  return (
    <div className={cn('flex flex-1 min-h-0 h-full border border-[var(--outline)] rounded-md overflow-hidden bg-[var(--surface)]', className)}>
      <ComparisonPane label={labelBaseline} sublabel="From baseline">
        <ComparisonImageView src={baselineUrl} alt={labelBaseline} zoom={scale} />
      </ComparisonPane>
      <div className="w-px bg-[var(--outline)] shrink-0" />
      <ComparisonPane label={labelCurrent} sublabel={changesSublabel}>
        <DiffHighlightFrame currentUrl={currentUrl} diffOverlayUrl={diffOverlayUrl} showDiff={showDiffOverlay} zoom={scale} fill className="h-full w-full" alt={labelCurrent} />
      </ComparisonPane>
    </div>
  );
}
