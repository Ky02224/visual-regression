import { renderHook } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { useGroupedRuns } from './useGroupedRuns';

// This hook is the adapter between the API's raw run records and every run list
// in the UI. The backend writes some fields under two different names across
// versions (mismatch/mismatch_pct, ai_label/aiLabel, id/run), so the mapping
// has fallbacks that silently produce zeros and blanks when they stop matching.

const raw = (over: Record<string, unknown> = {}) => ({
  run: 'run-1',
  case_name: 'home',
  url: 'https://example.com/',
  mismatch_pct: 12.5,
  status: 'FAIL',
  ...over,
});

const group = (runs: unknown[], filter?: (r: any) => boolean) =>
  renderHook(() => useGroupedRuns(runs as any[], filter)).result.current;

describe('useGroupedRuns', () => {
  it('returns nothing for no runs', () => {
    expect(group([])).toEqual([]);
  });

  it('tolerates undefined', () => {
    expect(renderHook(() => useGroupedRuns(undefined)).result.current).toEqual([]);
  });

  it('groups runs by url', () => {
    const groups = group([
      raw({ run: 'a', url: 'https://a.test/' }),
      raw({ run: 'b', url: 'https://b.test/' }),
      raw({ run: 'c', url: 'https://a.test/' }),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups.find(g => g.url === 'https://a.test/')?.runs).toHaveLength(2);
  });

  it('buckets a run with no url under Unknown rather than dropping it', () => {
    // Losing a run from the list entirely would be worse than showing it
    // ungrouped — the reviewer would never know it existed.
    const groups = group([raw({ url: undefined })]);
    expect(groups[0].url).toBe('Unknown');
  });

  it('applies the filter before grouping', () => {
    const groups = group(
      [raw({ run: 'a', build_id: 'b1' }), raw({ run: 'b', build_id: 'b2' })],
      r => r.build_id === 'b1'
    );
    expect(groups[0].runs).toHaveLength(1);
    expect(groups[0].runs[0].id).toBe('a');
  });

  describe('field mapping', () => {
    it('falls back from id to run', () => {
      expect(group([raw({ id: undefined, run: 'run-42' })])[0].runs[0].id).toBe('run-42');
    });

    it('prefers an explicit id', () => {
      expect(group([raw({ id: 'explicit', run: 'run-42' })])[0].runs[0].id).toBe('explicit');
    });

    it('falls back from name to case_name', () => {
      expect(group([raw({ name: undefined, case_name: 'checkout' })])[0].runs[0].name).toBe('checkout');
    });

    it('reads mismatch from either field name', () => {
      expect(group([raw({ mismatch: 5, mismatch_pct: undefined })])[0].runs[0].mismatch).toBe(5);
      expect(group([raw({ mismatch: undefined, mismatch_pct: 7.5 })])[0].runs[0].mismatch).toBe(7.5);
    });

    it('coerces mismatch to a number', () => {
      // Rendering a string here breaks the numeric sort on the runs table.
      expect(group([raw({ mismatch_pct: '3.5' })])[0].runs[0].mismatch).toBe(3.5);
    });

    it('defaults a missing mismatch to 0 rather than NaN', () => {
      expect(group([raw({ mismatch: undefined, mismatch_pct: undefined })])[0].runs[0].mismatch).toBe(0);
    });

    it('keeps a zero mismatch as 0', () => {
      // `??` rather than `||` matters here: a genuinely identical run has
      // mismatch 0, and `||` would replace it with the fallback.
      expect(group([raw({ mismatch_pct: 0 })])[0].runs[0].mismatch).toBe(0);
    });

    it('labels missing browser, device and locale as Unknown', () => {
      const run = group([raw()])[0].runs[0];
      expect(run.browser).toBe('Unknown');
      expect(run.device).toBe('Unknown');
      expect(run.locale).toBe('Unknown');
    });

    it('reads the AI label from either field name', () => {
      expect(group([raw({ ai_label: 'layout-issue' })])[0].runs[0].aiLabel).toBe('layout-issue');
      expect(group([raw({ aiLabel: 'text-issue' })])[0].runs[0].aiLabel).toBe('text-issue');
    });

    it('reads low confidence from the nested assessment', () => {
      // The uncertainty flag drives the review queue; missing it would hide
      // exactly the runs a human most needs to look at.
      const nested = group([raw({ ai_assessment: { low_confidence: true } })])[0].runs[0];
      expect(nested.lowConfidence).toBe(true);
    });

    it('prefers a top-level low_confidence flag', () => {
      const run = group([raw({ low_confidence: true, ai_assessment: { low_confidence: false } })])[0].runs[0];
      expect(run.lowConfidence).toBe(true);
    });

    it('defaults low confidence to false', () => {
      expect(group([raw()])[0].runs[0].lowConfidence).toBe(false);
    });

    it('preserves the raw status alongside the normalised review status', () => {
      const run = group([raw({ status: 'FAIL' })])[0].runs[0];
      expect(run.status).toBe('FAIL');
      expect(run.reviewStatus).toBeTruthy();
    });
  });
});
