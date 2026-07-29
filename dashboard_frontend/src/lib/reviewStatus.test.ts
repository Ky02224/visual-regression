import { describe, expect, it } from 'vitest';
import { normalizeReviewStatus, reviewStatusBadgeClass, mismatchPctClass, reviewBorderClass } from './reviewStatus';

describe('normalizeReviewStatus', () => {
  it('passes through already-canonical statuses', () => {
    expect(normalizeReviewStatus('no_changes')).toBe('no_changes');
    expect(normalizeReviewStatus('approved')).toBe('approved');
    expect(normalizeReviewStatus('rejected')).toBe('rejected');
    expect(normalizeReviewStatus('unreviewed')).toBe('unreviewed');
  });

  it('maps legacy pixel-diff statuses onto the review workflow', () => {
    expect(normalizeReviewStatus('passed')).toBe('no_changes');
    expect(normalizeReviewStatus('attention')).toBe('unreviewed');
    expect(normalizeReviewStatus('pending')).toBe('unreviewed');
    expect(normalizeReviewStatus('failed')).toBe('unreviewed');
  });

  it('is case-insensitive', () => {
    expect(normalizeReviewStatus('APPROVED')).toBe('approved');
  });

  it('defaults unknown/missing values to unreviewed rather than crashing', () => {
    expect(normalizeReviewStatus(undefined)).toBe('unreviewed');
    expect(normalizeReviewStatus(null)).toBe('unreviewed');
    expect(normalizeReviewStatus('garbage')).toBe('unreviewed');
    expect(normalizeReviewStatus(123)).toBe('unreviewed');
  });
});

describe('reviewStatusBadgeClass', () => {
  it('gives no_changes and approved the same green treatment', () => {
    expect(reviewStatusBadgeClass('no_changes')).toBe(reviewStatusBadgeClass('approved'));
  });

  it('gives rejected a red treatment distinct from approved', () => {
    expect(reviewStatusBadgeClass('rejected')).not.toBe(reviewStatusBadgeClass('approved'));
    expect(reviewStatusBadgeClass('rejected')).toContain('red');
  });
});

describe('mismatchPctClass', () => {
  it('flags >=5% mismatch as red regardless of review status', () => {
    expect(mismatchPctClass(5)).toContain('red');
    expect(mismatchPctClass(12.4)).toContain('red');
  });

  it('flags 1-5% mismatch as orange', () => {
    expect(mismatchPctClass(1)).toContain('orange');
    expect(mismatchPctClass(4.99)).toContain('orange');
  });

  it('flags <1% mismatch as green', () => {
    expect(mismatchPctClass(0)).toContain('green');
    expect(mismatchPctClass(0.99)).toContain('green');
  });

  it('treats the 1% and 5% boundaries as inclusive on the higher-severity side', () => {
    expect(mismatchPctClass(1)).not.toContain('green');
    expect(mismatchPctClass(5)).not.toContain('orange');
  });
});

describe('reviewBorderClass', () => {
  it('gives each status a distinct left-border accent', () => {
    const classes = new Set([
      reviewBorderClass('rejected'),
      reviewBorderClass('unreviewed'),
      reviewBorderClass('approved'),
    ]);
    expect(classes.size).toBe(3);
  });

  it('treats approved and no_changes identically', () => {
    expect(reviewBorderClass('approved')).toBe(reviewBorderClass('no_changes'));
  });
});
