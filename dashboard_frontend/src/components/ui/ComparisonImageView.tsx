import React from 'react';
import { cn } from '../../lib/utils';

type Metrics = { cw: number; ch: number; iw: number; ih: number };

function fitSize(m: Metrics, zoom: number) {
  const fitScale = Math.min(m.cw / m.iw, m.ch / m.ih);
  const scale = fitScale * zoom;
  return { w: Math.max(1, Math.round(m.iw * scale)), h: Math.max(1, Math.round(m.ih * scale)) };
}

export function ComparisonImageView({ src, alt, zoom = 1, className, onError }: { src: string; alt: string; zoom?: number; className?: string; onError?: () => void }) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const imgRef = React.useRef<HTMLImageElement>(null);
  const [metrics, setMetrics] = React.useState<Metrics | null>(null);
  const naturalSizeRef = React.useRef<{ iw: number; ih: number } | null>(null);

  const measure = React.useCallback((iw: number, ih: number) => {
    naturalSizeRef.current = { iw, ih };
    const el = containerRef.current;
    if (!el || !iw || !ih) return;
    const cw = el.clientWidth;
    const ch = el.clientHeight;
    if (cw < 2 || ch < 2) {
      requestAnimationFrame(() => {
        const el2 = containerRef.current;
        if (!el2) return;
        const cw2 = el2.clientWidth;
        const ch2 = el2.clientHeight;
        if (cw2 >= 2 && ch2 >= 2) setMetrics({ cw: cw2, ch: ch2, iw, ih });
      });
      return;
    }
    setMetrics({ cw, ch, iw, ih });
  }, []);

  React.useEffect(() => {
    setMetrics(null);
    naturalSizeRef.current = null;
  }, [src]);

  // Check if image is already cached/complete and trigger measure
  React.useEffect(() => {
    const img = imgRef.current;
    if (img && img.complete && img.naturalWidth) {
      measure(img.naturalWidth, img.naturalHeight);
    }
  }, [src, measure]);

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => {
      const iw = naturalSizeRef.current?.iw;
      const ih = naturalSizeRef.current?.ih;
      if (!iw || !ih) return;
      const cw = el.clientWidth;
      const ch = el.clientHeight;
      if (cw < 2 || ch < 2) return;
      setMetrics({ cw, ch, iw, ih });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const size = metrics ? fitSize(metrics, zoom) : null;

  React.useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.scrollLeft = 0;
    el.scrollTop = 0;
  }, [zoom, src, size?.w, size?.h]);

  const canScroll = size && metrics ? size.w > metrics.cw || size.h > metrics.ch : false;

  return (
    <div
      ref={containerRef}
      className={cn(
        'absolute inset-0 min-h-0 min-w-0',
        canScroll ? 'overflow-auto overscroll-contain' : 'overflow-hidden flex items-center justify-center',
        className,
      )}
    >
      {size ? (
        <div style={{ width: size.w, height: size.h, flexShrink: 0 }} className={canScroll ? 'inline-block' : undefined}>
          <img
            src={src}
            alt={alt}
            width={size.w}
            height={size.h}
            className="block select-none max-w-none max-h-none"
            referrerPolicy="no-referrer"
            draggable={false}
            onLoad={(e) => measure(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)}
            onError={onError}
          />
        </div>
      ) : (
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          className="w-full h-full object-contain"
          referrerPolicy="no-referrer"
          onLoad={(e) => measure(e.currentTarget.naturalWidth, e.currentTarget.naturalHeight)}
          onError={onError}
        />
      )}
    </div>
  );
}
