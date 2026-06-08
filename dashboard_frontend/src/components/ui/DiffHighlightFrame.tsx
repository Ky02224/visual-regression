import React from 'react';
import { cn } from '../../lib/utils';
import { ComparisonImageView } from './ComparisonImageView';

type Props = {
  currentUrl: string;
  diffOverlayUrl?: string;
  showDiff?: boolean;
  zoom?: number;
  fill?: boolean;
  aspectRatio?: string;
  className?: string;
  alt?: string;
};

/**
 * Percy-style diff toggle: swap to server-generated diff_overlay.png (no canvas).
 * Avoids CORS/taint issues and blank screen while compositing.
 */
export function DiffHighlightFrame({ currentUrl, diffOverlayUrl, showDiff = false, zoom = 1, fill = false, aspectRatio, className, alt = 'Screenshot' }: Props) {
  const [overlayFailed, setOverlayFailed] = React.useState(false);

  React.useEffect(() => {
    setOverlayFailed(false);
  }, [currentUrl, diffOverlayUrl, showDiff]);

  const useOverlay = showDiff && !!diffOverlayUrl && !overlayFailed;
  const src = useOverlay ? diffOverlayUrl! : currentUrl;

  return (
    <div
      style={!fill && aspectRatio ? { aspectRatio } : undefined}
      className={cn('relative bg-stone-100 dark:bg-zinc-800', fill ? 'w-full h-full min-h-0 overflow-hidden' : 'w-full overflow-hidden', className)}
    >
      <ComparisonImageView
        key={src}
        src={src}
        alt={alt}
        zoom={zoom}
        onError={useOverlay ? () => setOverlayFailed(true) : undefined}
      />
    </div>
  );
}
