import React from 'react';
import { ImageOff } from 'lucide-react';
import { cn, parseAspectRatio } from '../../lib/utils';
import { Button } from './Button';

function ImageFrameInner({ src, alt, aspectRatio = '16/10', fill = false, className, onRetry }: { src: string; alt: string; aspectRatio?: string; fill?: boolean; className?: string; onRetry?: () => void }) {
  const [state, setState] = React.useState<'loading' | 'loaded' | 'error'>('loading');
  const imgRef = React.useRef<HTMLImageElement>(null);
  const ratio = parseAspectRatio(aspectRatio);

  React.useEffect(() => {
    setState('loading');
    const img = imgRef.current;
    if (img?.complete) {
      setState(img.naturalWidth > 0 ? 'loaded' : 'error');
    }
  }, [src]);

  return (
    <div className={cn('relative overflow-hidden bg-stone-100 dark:bg-zinc-800 flex items-center justify-center', fill ? 'w-full h-full min-h-0' : 'w-full', className)} style={fill ? undefined : { aspectRatio: ratio }}>
      {state === 'loading' && <div className="absolute inset-0 animate-shimmer" aria-hidden />}
      {state === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-4">
          <ImageOff className="w-6 h-6 text-stone-400" />
          <p className="text-xs text-[var(--on-surface-variant)]">Screenshot unavailable</p>
          {onRetry && <Button variant="ghost" size="sm" onClick={onRetry}>Retry</Button>}
        </div>
      )}
      <img
        ref={imgRef}
        src={src}
        alt={alt}
        loading="lazy"
        decoding="async"
        className={cn('w-full h-full object-contain object-center', state !== 'loaded' && 'opacity-0')}
        referrerPolicy="no-referrer"
        onLoad={() => setState('loaded')}
        onError={() => setState('error')}
      />
    </div>
  );
}

export function ImageFrame(props: { src: string; alt: string; aspectRatio?: string; fill?: boolean; className?: string; onRetry?: () => void }) {
  return <ImageFrameInner key={props.src} {...props} />;
}
