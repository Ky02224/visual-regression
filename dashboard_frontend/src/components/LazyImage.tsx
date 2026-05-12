/**
 * Lazy-loaded image component with error handling
 */

import React from 'react';
import { Image as ImageIcon } from 'lucide-react';

interface LazyImageProps {
  src: string;
  alt: string;
  className?: string;
  width?: number | string;
  height?: number | string;
  loading?: 'lazy' | 'eager';
  onError?: () => void;
}

export const LazyImage: React.FC<LazyImageProps> = ({
  src,
  alt,
  className = '',
  width,
  height,
  loading = 'lazy',
  onError,
}) => {
  const [loaded, setLoaded] = React.useState(false);
  const [error, setError] = React.useState(false);
  const [imageSrc, setImageSrc] = React.useState<string | null>(null);

  React.useEffect(() => {
    // Create image element for preloading
    const img = new Image();
    img.src = src;
    
    img.onload = () => {
      setImageSrc(src);
      setLoaded(true);
    };

    img.onerror = () => {
      setError(true);
      if (onError) {
        onError();
      }
    };
  }, [src, onError]);

  if (error) {
    return (
      <div
        className={`flex items-center justify-center bg-slate-100 dark:bg-slate-800 ${className}`}
        style={{ width, height }}
      >
        <div className="flex flex-col items-center gap-2">
          <ImageIcon className="w-8 h-8 text-slate-400 dark:text-slate-600" />
          <span className="text-xs text-slate-500 dark:text-slate-500">Failed to load</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative overflow-hidden ${!loaded ? 'bg-slate-100 dark:bg-slate-800' : ''} ${className}`} style={{ width, height }}>
      {!loaded && (
        <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white to-transparent dark:from-transparent dark:via-slate-700 dark:to-transparent animate-pulse" />
      )}
      {imageSrc && (
        <img
          src={imageSrc}
          alt={alt}
          className={`w-full h-full object-cover transition-opacity duration-300 ${loaded ? 'opacity-100' : 'opacity-0'}`}
          loading={loading}
        />
      )}
    </div>
  );
};
