import React, { useState, useRef, useEffect } from 'react';
import { cn } from '../lib/utils';
import { Maximize2, Layers } from 'lucide-react';

interface ComparisonSliderProps {
  baselineUrl: string;
  currentUrl: string;
  labelBaseline?: string;
  labelCurrent?: string;
  compact?: boolean;
}

export function ComparisonSlider({ 
  baselineUrl, 
  currentUrl, 
  labelBaseline = "Baseline", 
  labelCurrent = "Current",
  compact = false
}: ComparisonSliderProps) {
  const [sliderPosition, setSliderPosition] = useState(50);
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMove = (clientX: number) => {
    if (!containerRef.current) return;
    const rect = containerRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(clientX - rect.left, rect.width));
    const percent = (x / rect.width) * 100;
    setSliderPosition(percent);
  };

  const onMouseMove = (e: MouseEvent) => {
    if (isDragging) handleMove(e.clientX);
  };

  const onTouchMove = (e: TouchEvent) => {
    if (isDragging) handleMove(e.touches[0].clientX);
  };

  const onMouseUp = () => setIsDragging(false);

  useEffect(() => {
    if (isDragging) {
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
      window.addEventListener('touchmove', onTouchMove);
      window.addEventListener('touchend', onMouseUp);
    } else {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onMouseUp);
    };
  }, [isDragging]);

  return (
    <div 
      ref={containerRef}
      className={cn(
        "relative bg-slate-100 dark:bg-slate-900 rounded-2xl overflow-hidden border border-slate-200 dark:border-slate-800 select-none group cursor-col-resize",
        compact ? "mx-auto w-full max-w-[360px] h-[680px]" : "w-full h-[320px] md:h-[380px]"
      )}
      onMouseDown={() => setIsDragging(true)}
      onTouchStart={() => setIsDragging(true)}
    >
      {/* Current Image (Bottom Layer) */}
      <img 
        src={currentUrl} 
        alt={labelCurrent}
        className="absolute inset-0 w-full h-full object-contain pointer-events-none"
        referrerPolicy="no-referrer"
      />

      {/* Baseline Image (Top Layer with Clip) */}
      <div 
        className="absolute inset-0 w-full h-full"
        style={{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }}
      >
        <img 
          src={baselineUrl} 
          alt={labelBaseline}
          className="absolute inset-0 w-full h-full object-contain pointer-events-none"
          referrerPolicy="no-referrer"
        />
        
        {/* Label Baseline */}
        <div className="absolute top-4 left-4 px-3 py-1 bg-black/50 backdrop-blur-md rounded-lg text-[10px] font-bold text-white uppercase tracking-widest pointer-events-none">
          {labelBaseline}
        </div>
      </div>

      {/* Label Current */}
      <div 
        className="absolute top-4 right-4 px-3 py-1 bg-indigo-600/60 backdrop-blur-md rounded-lg text-[10px] font-bold text-white uppercase tracking-widest pointer-events-none transition-opacity"
        style={{ opacity: sliderPosition > 85 ? 0 : 1 }}
      >
        {labelCurrent}
      </div>

      {/* Centered Instructions (Visible on hover if not dragging) */}
      {!isDragging && (
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-500">
          <div className="bg-white/10 backdrop-blur-xl border border-white/20 px-6 py-3 rounded-2xl flex items-center gap-3">
             <Layers className="w-5 h-5 text-white" />
             <span className="text-white text-xs font-bold uppercase tracking-widest">Drag to Compare</span>
          </div>
        </div>
      )}

      {/* Slider Handle */}
      <div 
        className="absolute inset-y-0 z-10 w-1 bg-white shadow-[0_0_15px_rgba(0,0,0,0.5)] flex items-center justify-center"
        style={{ left: `${sliderPosition}%` }}
      >
        <div className="w-8 h-8 bg-white rounded-full shadow-2xl flex items-center justify-center -ml-0.5 border-4 border-slate-100 dark:border-slate-900 group-active:scale-125 transition-transform">
          <div className="flex gap-0.5">
            <div className="w-0.5 h-3 bg-slate-300 rounded-full" />
            <div className="w-0.5 h-3 bg-slate-300 rounded-full" />
          </div>
        </div>
      </div>

      {/* Expand Button (Decorative for now) */}
      <button className="absolute bottom-4 right-4 p-2 bg-black/30 hover:bg-black/50 text-white rounded-lg transition-colors backdrop-blur-md">
        <Maximize2 className="w-4 h-4" />
      </button>
    </div>
  );
}
