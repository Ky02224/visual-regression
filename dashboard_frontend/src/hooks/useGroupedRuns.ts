import React from 'react';
import { TestRun } from '../types';
import { normalizeReviewStatus } from '../lib/reviewStatus';

export interface GroupedRuns {
  url: string;
  runs: TestRun[];
}

function mapRun(r: any): TestRun {
  return {
    ...r,
    id: r.id || r.run,
    name: r.name || r.case_name || r.id,
    mismatch: Number(r.mismatch ?? r.mismatch_pct ?? 0),
    reviewStatus: normalizeReviewStatus(r.review_status ?? r.status),
    status: r.status,
    browser: r.browser || 'Unknown',
    device: r.device || 'Unknown',
    locale: r.locale || 'Unknown',
    aiLabel: r.ai_label ?? r.aiLabel,
    lowConfidence: r.low_confidence ?? r.ai_assessment?.low_confidence ?? false,
  };
}

/**
 * Maps raw dashboard API run records into TestRun[] and groups them by url.
 * `filter` narrows the raw records before mapping (e.g. to a single build).
 */
export function useGroupedRuns(runs: any[] | undefined, filter?: (r: any) => boolean): GroupedRuns[] {
  return React.useMemo(() => {
    const source = runs || [];
    const filtered = filter ? source.filter(filter) : source;
    const groups: Record<string, TestRun[]> = {};
    filtered.forEach((r: any) => {
      const urlStr = r.url || 'Unknown';
      if (!groups[urlStr]) groups[urlStr] = [];
      groups[urlStr].push(mapRun(r));
    });
    return Object.keys(groups).map(url => ({ url, runs: groups[url] }));
  }, [runs, filter]);
}
