export function parseUrl(url: string): { host: string; path: string } {
  try {
    const u = new URL(url.startsWith('http') ? url : `https://${url}`);
    return { host: u.host, path: u.pathname + (u.search || '') };
  } catch {
    const slash = url.indexOf('/');
    if (slash !== -1) return { host: url.slice(0, slash), path: url.slice(slash) };
    return { host: url, path: '/' };
  }
}

export function relativeTime(ts: string | number | null | undefined): string | null {
  if (!ts) return null;
  const d = typeof ts === 'number' ? new Date(ts < 1e12 ? ts * 1000 : ts) : new Date(ts);
  if (isNaN(d.getTime())) return null;
  const diff = Math.floor((Date.now() - d.getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}
