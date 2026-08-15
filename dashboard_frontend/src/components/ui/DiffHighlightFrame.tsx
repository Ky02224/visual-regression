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
 * Percy-style diff toggle: swap to server-generated diff_overlay.webp (no canvas).
 * Avoids CORS/taint issues and blank screen while compositing.
 */
export function DiffHighlightFrame({ currentUrl, diffOverlayUrl, showDiff = false, zoom = 1, fill = false, aspectRatio, className, alt = 'Screenshot' }: Props) {
  const [overlayFailed, setOverlayFailed] = React.useState(false);
  const [naturalWidth, setNaturalWidth] = React.useState<number | null>(null);

  React.useEffect(() => {
    setOverlayFailed(false);
  }, [currentUrl, diffOverlayUrl, showDiff]);

  const useOverlay = showDiff && !!diffOverlayUrl && !overlayFailed;
  const src = useOverlay ? diffOverlayUrl! : currentUrl;
  const handleError = useOverlay ? () => setOverlayFailed(true) : undefined;

  // Cached images can be `complete` before React attaches onLoad, so read the
  // natural size off the node as well.
  const measureRef = React.useCallback((el: HTMLImageElement | null) => {
    if (el && el.complete && el.naturalWidth) setNaturalWidth(el.naturalWidth);
  }, []);

  // Without `fill` or an aspect ratio there is no box to fit into: ComparisonImageView
  // positions itself `absolute inset-0`, which would leave this wrapper zero-height and
  // the image invisible. Let the image size itself instead so the wrapper hugs it —
  // the overlay view pins comments at percentages of that wrapper.
  if (!fill && !aspectRatio) {
    return (
      <img
        key={src}
        ref={measureRef}
        src={src}
        alt={alt}
        className={cn('block select-none', className, zoom > 1 && 'max-h-none max-w-none')}
        style={zoom > 1 && naturalWidth ? { width: naturalWidth * zoom, height: 'auto' } : undefined}
        referrerPolicy="no-referrer"
        draggable={false}
        onLoad={(e) => setNaturalWidth(e.currentTarget.naturalWidth)}
        onError={handleError}
      />
    );
  }

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
        onError={handleError}
      />
    </div>
  );
}
