import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { parseUrl, relativeTime } from './format';

// Every run row in the dashboard shows a host, a path and a relative timestamp.
// These are pure formatting functions with a fallback path that only fires on
// malformed input — exactly the branch that never gets exercised by hand.

describe('parseUrl', () => {
  it('splits a full URL into host and path', () => {
    expect(parseUrl('https://example.com/products/list')).toEqual({
      host: 'example.com',
      path: '/products/list',
    });
  });

  it('keeps the port in the host', () => {
    // Runs against a local dashboard are all on :8130; dropping the port would
    // make every one of them look like the same host.
    expect(parseUrl('http://127.0.0.1:8130/demo/index.html').host).toBe('127.0.0.1:8130');
  });

  it('keeps the query string in the path', () => {
    // ?defect=missing-cta is what distinguishes a defect case from its control.
    expect(parseUrl('http://host/demo/index.html?defect=missing-cta').path).toBe(
      '/demo/index.html?defect=missing-cta'
    );
  });

  it('assumes https when no scheme is given', () => {
    expect(parseUrl('example.com/page')).toEqual({ host: 'example.com', path: '/page' });
  });

  it('reports a bare host with a root path', () => {
    expect(parseUrl('example.com')).toEqual({ host: 'example.com', path: '/' });
  });

  it('reports the root path for a URL with no path', () => {
    expect(parseUrl('https://example.com')).toEqual({ host: 'example.com', path: '/' });
  });

  it('falls back to a manual split rather than throwing on malformed input', () => {
    // A row with an unparseable URL should still render.
    const result = parseUrl('not a url/with/slashes');
    expect(result.host).toBeTruthy();
    expect(result.path.startsWith('/')).toBe(true);
  });

  it('handles an empty string without throwing', () => {
    expect(() => parseUrl('')).not.toThrow();
  });
});

describe('relativeTime', () => {
  const NOW = new Date('2026-08-03T12:00:00Z').getTime();

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(NOW);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('reports seconds under a minute', () => {
    expect(relativeTime(new Date(NOW - 30_000).toISOString())).toBe('30s ago');
  });

  it('reports minutes under an hour', () => {
    expect(relativeTime(new Date(NOW - 5 * 60_000).toISOString())).toBe('5m ago');
  });

  it('reports hours under a day', () => {
    expect(relativeTime(new Date(NOW - 3 * 3_600_000).toISOString())).toBe('3h ago');
  });

  it('reports days beyond that', () => {
    expect(relativeTime(new Date(NOW - 2 * 86_400_000).toISOString())).toBe('2d ago');
  });

  it('accepts a unix timestamp in seconds', () => {
    // The API returns created_at in seconds; treating it as milliseconds would
    // date every run to 1970.
    expect(relativeTime(Math.floor(NOW / 1000) - 120)).toBe('2m ago');
  });

  it('accepts a unix timestamp in milliseconds', () => {
    expect(relativeTime(NOW - 120_000)).toBe('2m ago');
  });

  it('returns null for a missing value', () => {
    expect(relativeTime(null)).toBeNull();
    expect(relativeTime(undefined)).toBeNull();
    expect(relativeTime('')).toBeNull();
  });

  it('returns null for an unparseable date rather than showing NaN', () => {
    expect(relativeTime('not-a-date')).toBeNull();
  });

  it('crosses each boundary at the right point', () => {
    expect(relativeTime(new Date(NOW - 59_000).toISOString())).toBe('59s ago');
    expect(relativeTime(new Date(NOW - 60_000).toISOString())).toBe('1m ago');
    expect(relativeTime(new Date(NOW - 3_599_000).toISOString())).toBe('59m ago');
    expect(relativeTime(new Date(NOW - 3_600_000).toISOString())).toBe('1h ago');
  });
});
