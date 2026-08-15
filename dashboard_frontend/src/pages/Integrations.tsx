import React from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Terminal,
  Key,
  Copy,
  Check,
  Eye,
  EyeOff,
  Cpu,
  Github,
  Gitlab,
  Webhook,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ShieldCheck,
  Link2,
  ExternalLink,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { cn } from '../lib/utils';
import { useRole } from '../context/RoleContext';

type IntegrationConfig = {
  webhook_url?: string;
  webhook_threshold?: number;
  api_key?: string;
  webhook_connected?: boolean;
  activity_count?: number;
  github_configured?: boolean;
};

type GithubStatus = {
  configured?: boolean;
  connected?: boolean;
  login?: string;
  avatar_url?: string;
  profile_url?: string;
  scopes?: string[];
  connected_at?: number;
  repo_url?: string;
  redirect_uri?: string;
};

type ActivityItem = {
  id: string;
  message: string;
  branch: string;
  status: 'success' | 'failed';
  timestamp: number;
};

type Notice = {
  tone: 'success' | 'error' | 'info';
  message: string;
};

function NoticeBanner({ notice }: { notice: Notice | null }) {
  if (!notice) return null;

  return (
    <div
      className={cn(
        'rounded-md border px-4 py-3 text-sm font-medium',
        notice.tone === 'success' && 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800/40 dark:bg-emerald-950/30 dark:text-emerald-300',
        notice.tone === 'error' && 'border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-800/40 dark:bg-rose-950/30 dark:text-rose-300',
        notice.tone === 'info' && 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800/40 dark:bg-blue-950/30 dark:text-blue-300',
      )}
    >
      {notice.message}
    </div>
  );
}

function CopyIconButton({ value, label, disabled = false }: { value: string; label: string; disabled?: boolean }) {
  const [copied, setCopied] = React.useState(false);

  const handleCopy = async () => {
    if (!value || disabled) return;
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <button
      type="button"
      onClick={handleCopy}
      disabled={disabled}
      className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-600 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white"
      aria-label={label}
    >
      {copied ? <Check className="h-4 w-4 text-emerald-500" /> : <Copy className="h-4 w-4" />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

export function Integrations() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [pageNotice, setPageNotice] = React.useState<Notice | null>(null);

  React.useEffect(() => {
    const githubConnected = searchParams.get('github');
    const githubError = searchParams.get('github_error');
    if (githubConnected === 'connected') {
      setPageNotice({ tone: 'success', message: 'GitHub OAuth connected successfully.' });
      setSearchParams({}, { replace: true });
      return;
    }
    if (githubError) {
      setPageNotice({ tone: 'error', message: decodeURIComponent(githubError) });
      setSearchParams({}, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  return (
    <div className="min-h-screen p-8">
      <div className="mx-auto max-w-6xl space-y-10">
        <header className="space-y-3 border-b border-slate-200 pb-8 dark:border-slate-800">
          <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-semibold font-medium text-slate-500 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300">
            <Link2 className="h-3.5 w-3.5" />
            Integrations
          </div>
          <div>
            <h2 className="text-3xl font-bold text-[var(--on-surface)]">CI/CD Integrations</h2>
            <p className="mt-2 max-w-3xl text-sm font-medium text-[var(--on-surface-variant)]">
              Connect your dashboard to GitHub and webhook-based alerts so failed visual regressions can flow into a real release workflow.
            </p>
          </div>
        </header>

        <NoticeBanner notice={pageNotice} />


        <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
          <GitHubConnectionModule />
          <ApiTokensModule />
          <WebhooksModule />
          <div className="lg:col-span-2">
            <PipelineGeneratorModule />
          </div>
          <div className="lg:col-span-2">
            <PipelineFeedModule />
          </div>
        </div>
      </div>
    </div>
  );
}

function GitHubConnectionModule() {
  const { role } = useRole();
  const [status, setStatus] = React.useState<GithubStatus | null>(null);
  const [notice, setNotice] = React.useState<Notice | null>(null);
  const [loading, setLoading] = React.useState(true);
  const [connecting, setConnecting] = React.useState(false);
  const [disconnecting, setDisconnecting] = React.useState(false);
  const [confirmDisconnect, setConfirmDisconnect] = React.useState(false);

  const loadStatus = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/integrations/github/status');
      const data: GithubStatus = await res.json();
      setStatus(data);
    } catch {
      setNotice({ tone: 'error', message: 'Unable to load GitHub connection status.' });
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  const handleConnect = async () => {
    setConnecting(true);
    setNotice(null);
    try {
      const res = await fetch('/api/integrations/github/connect', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Unable to start GitHub OAuth.');
      }
      window.location.href = data.authorize_url;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to start GitHub OAuth.';
      setNotice({ tone: 'error', message });
      setConnecting(false);
    }
  };

  const handleDisconnect = async () => {
    setConfirmDisconnect(false);
    setDisconnecting(true);
    setNotice(null);
    try {
      const res = await fetch('/api/integrations/github/disconnect', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Unable to disconnect GitHub.');
      }
      setNotice({ tone: 'success', message: 'GitHub disconnected.' });
      await loadStatus();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to disconnect GitHub.';
      setNotice({ tone: 'error', message });
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <section className="rounded-md border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-100 bg-slate-50 text-accent dark:border-slate-700 dark:bg-slate-800">
            <Github className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-[var(--on-surface)]">GitHub OAuth</h3>
            <p className="text-xs font-medium text-[var(--on-surface-variant)]">Connect a GitHub account so this dashboard can identify the linked engineering workflow.</p>
          </div>
        </div>
        <div
          className={cn(
            'rounded-full px-3 py-1 text-[11px] font-semibold font-medium',
            status?.connected
              ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300'
              : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300'
          )}
        >
          {status?.connected ? 'Connected' : 'Not connected'}
        </div>
      </div>

      <NoticeBanner notice={notice} />

      <div className="mt-5 rounded-md border border-slate-100 bg-slate-50 p-5 dark:border-slate-800 dark:bg-slate-950">
        {loading ? (
          <p className="text-sm font-medium text-[var(--on-surface-variant)]">Loading GitHub connection...</p>
        ) : !status?.configured ? (
          <div className="space-y-3">
            <p className="text-sm font-semibold text-slate-700 dark:text-slate-200">GitHub OAuth is not configured on the dashboard server yet.</p>
            <p className="text-xs font-medium text-[var(--on-surface-variant)]">
              Set <code className="font-mono">GITHUB_OAUTH_CLIENT_ID</code> and <code className="font-mono">GITHUB_OAUTH_CLIENT_SECRET</code> before using this feature.
            </p>
            <p className="text-xs font-medium text-[var(--on-surface-variant)]">
              Redirect URI: <code className="font-mono break-all">{status?.redirect_uri || 'http://127.0.0.1:8130/api/integrations/github/callback'}</code>
            </p>
          </div>
        ) : status.connected ? (
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div className="flex items-center gap-4">
              {status.avatar_url ? (
                <img src={status.avatar_url} alt={status.login || 'GitHub avatar'} className="h-14 w-14 rounded-md object-cover ring-1 ring-slate-200 dark:ring-slate-700" />
              ) : (
                <div className="flex h-14 w-14 items-center justify-center rounded-md bg-slate-200 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                  <Github className="h-6 w-6" />
                </div>
              )}
              <div className="space-y-1">
                <p className="text-sm font-bold text-[var(--on-surface)]">{status.login || 'Connected account'}</p>
                <p className="text-xs font-medium text-[var(--on-surface-variant)]">
                  {status.connected_at ? `Connected ${new Date(status.connected_at * 1000).toLocaleString()}` : 'Connected'}
                </p>
                {status.profile_url && (
                  <a href={status.profile_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-semibold text-blue-600 hover:text-blue-700 dark:text-blue-300 dark:hover:text-blue-200">
                    View GitHub profile
                    <ExternalLink className="h-3.5 w-3.5" />
                  </a>
                )}
              </div>
            </div>

            {confirmDisconnect ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-[var(--on-surface-variant)]">Disconnect GitHub?</span>
                <button type="button" onClick={() => setConfirmDisconnect(false)} className="rounded-xl border border-[var(--outline)] px-3 py-1.5 text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition">Cancel</button>
                <button type="button" onClick={handleDisconnect} disabled={disconnecting} className="rounded-xl bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 transition disabled:opacity-50">
                  {disconnecting ? 'Disconnecting...' : 'Confirm'}
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmDisconnect(true)}
                disabled={role !== 'admin' || disconnecting}
                className="rounded-xl border border-slate-200 px-4 py-2 text-xs font-bold font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-600"
              >
                Disconnect
              </button>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-sm font-medium text-slate-600 dark:text-slate-300">
              Start the GitHub OAuth flow to bind this dashboard to the GitHub identity you use for CI/CD and release review.
            </p>
            {status.repo_url && (
              <p className="text-xs font-medium text-[var(--on-surface-variant)]">
                Local repo: <span className="font-mono">{status.repo_url}</span>
              </p>
            )}
            <button
              type="button"
              onClick={handleConnect}
              disabled={role !== 'admin' || connecting}
              className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold font-medium text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-800"
            >
              {connecting ? 'Redirecting...' : 'Connect GitHub'}
            </button>
          </div>
        )}
      </div>
    </section>
  );
}

function ApiTokensModule() {
  const { role } = useRole();
  const [maskedKey, setMaskedKey] = React.useState('••••••••');
  const [revealedKey, setRevealedKey] = React.useState('');
  const [showKey, setShowKey] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [rotating, setRotating] = React.useState(false);
  const [confirmRotate, setConfirmRotate] = React.useState(false);
  const [revealing, setRevealing] = React.useState(false);
  const [notice, setNotice] = React.useState<Notice | null>(null);
  const [activityCount, setActivityCount] = React.useState(0);

  const loadConfig = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/integrations');
      const data: IntegrationConfig = await res.json();
      setMaskedKey(data.api_key || '••••••••');
      setActivityCount(data.activity_count || 0);
    } catch {
      setNotice({ tone: 'error', message: 'Unable to load integration settings from the dashboard server.' });
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleReveal = async () => {
    if (showKey) {
      setShowKey(false);
      return;
    }
    setRevealing(true);
    setNotice(null);
    try {
      const res = await fetch('/api/integrations/reveal-key', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Unable to reveal API key.');
      }
      setRevealedKey(data.api_key || '');
      setShowKey(true);
      setNotice({ tone: 'success', message: 'API key revealed. You can now copy it into your CI/CD secret store.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Unable to reveal API key.';
      setNotice({ tone: 'error', message });
    } finally {
      setRevealing(false);
    }
  };

  const handleRotate = async () => {
    setConfirmRotate(false);
    setRotating(true);
    setNotice(null);
    try {
      const res = await fetch('/api/integrations/rotate-key', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Failed to rotate API key.');
      }
      setRevealedKey(data.api_key || '');
      setShowKey(true);
      setMaskedKey(data.api_key || maskedKey);
      setNotice({ tone: 'success', message: 'API key rotated. Update your GitHub secret with the new value.' });
      await loadConfig();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to rotate API key.';
      setNotice({ tone: 'error', message });
    } finally {
      setRotating(false);
    }
  };

  const currentKey = showKey ? (revealedKey || maskedKey) : maskedKey;

  return (
    <section className="rounded-md border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-100 bg-slate-50 text-accent dark:border-slate-700 dark:bg-slate-800">
            <Key className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-[var(--on-surface)]">API access token</h3>
            <p className="text-xs font-medium text-[var(--on-surface-variant)]">Use this secret in GitHub Actions, Jenkins, or any pipeline that needs to call the dashboard.</p>
          </div>
        </div>
        <div className="rounded-full border border-slate-200 px-3 py-1 text-[11px] font-semibold font-medium text-slate-500 dark:border-slate-700 dark:text-slate-300">
          {activityCount} activity entries
        </div>
      </div>

      <NoticeBanner notice={notice} />

      <div className="mt-5 rounded-md border border-slate-200 bg-slate-950 p-5 dark:border-slate-700">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-[10px] font-bold font-medium text-slate-500">Production key</p>
            <p className="mt-1 text-xs font-medium text-[var(--on-surface-variant)]">Store this in your CI secret manager, not directly in code.</p>
          </div>
          <div className="flex items-center gap-2">
            <CopyIconButton value={showKey ? revealedKey : ''} label="Copy API key" disabled={!showKey || !revealedKey} />
            <button
              type="button"
              onClick={handleReveal}
              disabled={role !== 'admin' || revealing || loading}
              className="inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-slate-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
            >
              {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              {showKey ? 'Hide' : revealing ? 'Revealing...' : 'Reveal'}
            </button>
          </div>
        </div>
        <code className="block overflow-x-auto rounded-md bg-slate-900 px-4 py-4 text-sm text-blue-300">
          {loading ? 'Loading token...' : currentKey}
        </code>
      </div>

      <div className="mt-5 flex items-center justify-between gap-4 rounded-md border border-slate-100 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-950">
        <div className="flex items-center gap-3 text-sm font-medium text-slate-600 dark:text-slate-300">
          <ShieldCheck className="h-4 w-4 text-emerald-500" />
          Only admin can reveal or rotate the live token.
        </div>
        {confirmRotate ? (
          <div className="flex items-center gap-2">
            <span className="text-xs text-[var(--on-surface-variant)]">This will break existing CI secrets.</span>
            <button type="button" onClick={() => setConfirmRotate(false)} className="rounded-xl border border-[var(--outline)] px-3 py-1.5 text-xs font-bold text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800 transition">Cancel</button>
            <button type="button" onClick={handleRotate} disabled={rotating} className="rounded-xl bg-red-600 px-3 py-1.5 text-xs font-bold text-white hover:bg-red-700 transition disabled:opacity-50">
              {rotating ? 'Rotating...' : 'Confirm Rotate'}
            </button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setConfirmRotate(true)}
            disabled={role !== 'admin' || rotating}
            className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold font-medium text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-800"
          >
            Rotate key
          </button>
        )}
      </div>
    </section>
  );
}

function WebhooksModule() {
  const { role } = useRole();
  const [url, setUrl] = React.useState('');
  const [saving, setSaving] = React.useState(false);
  const [testing, setTesting] = React.useState(false);
  const [notice, setNotice] = React.useState<Notice | null>(null);
  const [connected, setConnected] = React.useState(false);

  const loadConfig = React.useCallback(async () => {
    try {
      const res = await fetch('/api/integrations');
      const data: IntegrationConfig = await res.json();
      setUrl(data.webhook_url || '');
      setConnected(Boolean(data.webhook_connected));
    } catch {
      setNotice({ tone: 'error', message: 'Unable to load webhook settings from the dashboard server.' });
    }
  }, []);

  React.useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleSave = async () => {
    setSaving(true);
    setNotice(null);
    try {
      const res = await fetch('/api/integrations/webhooks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ url, threshold: 0 }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Failed to save webhook configuration.');
      }
      setConnected(Boolean(url));
      setNotice({ tone: 'success', message: url ? 'Webhook saved. The dashboard can now send notifications to this endpoint.' : 'Webhook cleared.' });
      await loadConfig();
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Failed to save webhook configuration.';
      setNotice({ tone: 'error', message });
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    if (!url) {
      setNotice({ tone: 'info', message: 'Enter a webhook URL first, then run the test.' });
      return;
    }
    setTesting(true);
    setNotice(null);
    try {
      const res = await fetch('/api/integrations/test-webhook', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        credentials: 'include',
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        throw new Error(data.error || 'Webhook test failed.');
      }
      setNotice({ tone: 'success', message: data.message || 'Webhook test succeeded.' });
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Webhook test failed.';
      setNotice({ tone: 'error', message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <section className="rounded-md border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-100 bg-slate-50 text-accent dark:border-slate-700 dark:bg-slate-800">
            <Webhook className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-[var(--on-surface)]">Regression-detected webhook</h3>
            <p className="text-xs font-medium text-[var(--on-surface-variant)]">Connect one endpoint that should be notified whenever a failed visual regression is detected.</p>
          </div>
        </div>
        <div className={cn(
          'rounded-full px-3 py-1 text-[11px] font-semibold font-medium',
          connected ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-300'
        )}>
          {connected ? 'Connected' : 'Not connected'}
        </div>
      </div>

      <NoticeBanner notice={notice} />

      <div className="mt-5 space-y-5">
        <div className="space-y-2">
          <label className="text-[11px] font-semibold font-medium text-slate-500">Webhook URL</label>
          <input
            type="url"
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            placeholder="https://hooks.slack.com/services/..."
            className="w-full rounded-md border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-900 outline-none transition focus:border-blue-300 focus:ring-2 focus:ring-blue-100 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100 dark:focus:border-blue-500 dark:focus:ring-blue-950"
          />
        </div>

        <div className="rounded-md border border-slate-100 bg-slate-50 p-4 dark:border-slate-800 dark:bg-slate-950">
          <p className="text-[11px] font-semibold font-medium text-slate-500">Events</p>
          <p className="mt-2 text-sm font-bold text-[var(--on-surface)]">regression.detected</p>
          <p className="mt-1 text-xs font-medium text-[var(--on-surface-variant)]">
            Sent only when a compare result or suite case fails against the approved baseline.
          </p>
          <p className="mt-3 text-sm font-bold text-[var(--on-surface)]">comment.added</p>
          <p className="mt-1 text-xs font-medium text-[var(--on-surface-variant)]">
            Sent when a reviewer pins a comment to a run, so a question does not sit unread inside one report.
          </p>
        </div>
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={role !== 'admin' || saving}
          className="rounded-xl bg-slate-900 px-4 py-2 text-xs font-bold font-medium text-white transition hover:bg-black disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-800"
        >
          {saving ? 'Saving...' : 'Save webhook'}
        </button>
        <button
          type="button"
          onClick={handleTest}
          disabled={role !== 'admin' || testing || !url}
          className="rounded-xl border border-slate-200 px-4 py-2 text-xs font-bold font-medium text-slate-700 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-200 dark:hover:border-slate-600"
        >
          {testing ? 'Testing...' : 'Test webhook'}
        </button>
      </div>
    </section>
  );
}

function PipelineGeneratorModule() {
  const [activeTab, setActiveTab] = React.useState<'github' | 'gitlab' | 'jenkins'>('github');
  const [copied, setCopied] = React.useState(false);

  const snippets = {
    github: `name: visual-regression
on:
  push:
  pull_request:

jobs:
  visual-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: python -m pip install --upgrade pip
      - run: pip install -r requirements-dev.txt
      - run: python -m playwright install chromium
      - run: python -m pytest -q
      - run: python -m visual_regression.cli serve-demo --port 8123 &
      - run: python -m visual_regression.cli create-suite-baselines --suite suite.summaries.yaml --overwrite
      - run: python -m visual_regression.cli run-suite --suite suite.summaries.yaml --no-junit
        env:
          LENS_API_KEY: \${{ secrets.LENS_API_KEY }}`,
    gitlab: `visual_regression:
  image: python:3.11
  script:
    - pip install -r requirements-dev.txt
    - python -m playwright install chromium
    - python -m pytest -q
    - python -m visual_regression.cli serve-demo --port 8123 &
    - python -m visual_regression.cli create-suite-baselines --suite suite.summaries.yaml --overwrite
    - python -m visual_regression.cli run-suite --suite suite.summaries.yaml --no-junit
  variables:
    LENS_API_KEY: $LENS_API_KEY`,
    jenkins: `pipeline {
  agent any
  stages {
    stage('Visual Regression') {
      steps {
        bat 'pip install -r requirements-dev.txt'
        bat 'python -m playwright install chromium'
        bat 'python -m pytest -q'
        bat 'python -m visual_regression.cli serve-demo --port 8123'
        bat 'python -m visual_regression.cli create-suite-baselines --suite suite.summaries.yaml --overwrite'
        bat 'python -m visual_regression.cli run-suite --suite suite.summaries.yaml --no-junit'
      }
    }
  }
}`,
  } as const;

  const snippet = snippets[activeTab];

  const copySnippet = async () => {
    await navigator.clipboard.writeText(snippet);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  };

  return (
    <section className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="flex flex-col justify-between gap-6 border-b border-slate-100 p-8 dark:border-slate-800 md:flex-row md:items-center">
        <div className="flex items-center gap-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-100 bg-slate-50 text-accent dark:border-slate-700 dark:bg-slate-800">
            <Cpu className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-[var(--on-surface)]">Pipeline generator</h3>
            <p className="text-xs font-medium text-[var(--on-surface-variant)]">Copy a starter config and drop your token into your CI secret store.</p>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          {(['github', 'gitlab', 'jenkins'] as const).map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={cn(
                'rounded-xl px-4 py-2 text-xs font-bold font-medium transition',
                activeTab === tab
                  ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                  : 'border border-slate-200 text-slate-500 hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white'
              )}
            >
              {tab === 'github' && <Github className="mr-2 inline h-3.5 w-3.5" />}
              {tab === 'gitlab' && <Gitlab className="mr-2 inline h-3.5 w-3.5" />}
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-4 p-8">
        <div className="rounded-md border border-blue-100 bg-blue-50 px-4 py-3 text-sm font-medium text-blue-700 dark:border-blue-900/40 dark:bg-blue-950/30 dark:text-blue-200">
          Tip: add your live token as <code className="font-mono">LENS_API_KEY</code> in your CI/CD secret settings instead of hardcoding it into the file.
        </div>
        <div className="relative rounded-md bg-slate-950 p-6">
          <button
            type="button"
            onClick={copySnippet}
            className="absolute right-4 top-4 inline-flex items-center gap-2 rounded-xl border border-slate-700 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-slate-500 hover:text-white"
          >
            {copied ? <Check className="h-4 w-4 text-emerald-400" /> : <Copy className="h-4 w-4" />}
            {copied ? 'Copied' : 'Copy snippet'}
          </button>
          <pre className="overflow-x-auto whitespace-pre-wrap pr-28 text-sm leading-6 text-blue-300">{snippet}</pre>
        </div>
      </div>
    </section>
  );
}

function PipelineFeedModule() {
  const [runs, setRuns] = React.useState<ActivityItem[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [showAll, setShowAll] = React.useState(false);
  const [isCardExpanded, setIsCardExpanded] = React.useState(true);
  const [notice, setNotice] = React.useState<Notice | null>(null);

  const fetchActivity = React.useCallback(() => {
    setLoading(true);
    fetch('/api/integrations/activity')
      .then((res) => {
        if (!res.ok) throw new Error('Request failed');
        return res.json();
      })
      .then((data) => {
        setRuns(data.activity || []);
        setNotice(null);
        setLoading(false);
      })
      .catch(() => {
        setNotice({ tone: 'error', message: 'Unable to load integration activity.' });
        setLoading(false);
      });
  }, []);

  React.useEffect(() => {
    fetchActivity();
  }, [fetchActivity]);

  const visibleRuns = showAll ? runs : runs.slice(0, 5);

  return (
    <section className="rounded-md border border-slate-200 bg-white p-8 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      <div className="mb-8 flex items-center justify-between gap-4">
        <div
          className="flex items-center gap-4 cursor-pointer select-none focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50 rounded-lg"
          onClick={() => setIsCardExpanded(!isCardExpanded)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault();
              setIsCardExpanded(!isCardExpanded);
            }
          }}
          role="button"
          tabIndex={0}
          aria-expanded={isCardExpanded}
        >
          <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-slate-100 bg-slate-50 text-accent dark:border-slate-700 dark:bg-slate-800">
            <Terminal className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-bold text-[var(--on-surface)]">Recent integration activity</h3>
              {isCardExpanded ? <ChevronUp className="h-4 w-4 text-slate-400" /> : <ChevronDown className="h-4 w-4 text-slate-400" />}
            </div>
            <p className="text-xs font-medium text-[var(--on-surface-variant)]">See webhook saves, key rotations, and CI-triggered events in one place.</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isCardExpanded && (
            <button
              type="button"
              onClick={fetchActivity}
              disabled={loading}
              className="rounded-xl border border-slate-200 p-2 text-slate-500 transition hover:border-slate-300 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white"
            >
              <RefreshCw className={cn('h-5 w-5', loading && 'animate-spin')} />
            </button>
          )}
          <button
            type="button"
            onClick={() => setIsCardExpanded(!isCardExpanded)}
            className="rounded-xl border border-slate-200 p-2 text-slate-500 transition hover:border-slate-300 hover:text-slate-900 dark:border-slate-700 dark:text-slate-300 dark:hover:border-slate-600 dark:hover:text-white"
          >
            {isCardExpanded ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
          </button>
        </div>
      </div>

      {isCardExpanded && (
        <div className="space-y-4">
          <NoticeBanner notice={notice} />

          {loading && runs.length === 0 && (
            <div className="rounded-md border-2 border-dashed border-slate-200 px-6 py-10 text-center text-xs font-bold font-medium text-[var(--on-surface-variant)] dark:border-slate-700 dark:text-slate-500">
              Loading integration activity...
            </div>
          )}

          {!loading && !notice && runs.length === 0 && (
            <div className="rounded-md border-2 border-dashed border-slate-200 px-6 py-10 text-center text-sm font-medium text-slate-500 dark:border-slate-700 dark:text-[var(--on-surface-variant)]">
              No integration activity yet. Save a webhook, rotate a key, or run CI/CD once to populate this feed.
            </div>
          )}

          {visibleRuns.map((run) => (
            <div 
              key={run.id} 
              className="flex items-center justify-between gap-4 rounded-md border border-slate-100 p-4 transition hover:bg-slate-50 dark:border-slate-800 dark:hover:bg-slate-800/70"
            >
              <div className="flex items-center gap-4">
                <div className={cn(
                  'flex h-10 w-10 items-center justify-center rounded-full',
                  run.status === 'success' ? 'bg-emerald-50 text-emerald-500 dark:bg-emerald-950/40 dark:text-emerald-300' : 'bg-rose-50 text-rose-500 dark:bg-rose-950/40 dark:text-rose-300'
                )}>
                  {run.status === 'success' ? <CheckCircle2 className="h-5 w-5" /> : <XCircle className="h-5 w-5" />}
                </div>
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-bold text-[var(--on-surface)]">{run.message}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold font-medium text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                      {run.branch}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-xs font-medium text-[var(--on-surface-variant)]">
                    <span className="font-mono">#{run.id}</span>
                    <span className="inline-flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {new Date(run.timestamp * 1000).toLocaleString()}
                    </span>
                  </div>
                </div>
              </div>
              <AlertCircle className="h-4 w-4 text-slate-300 dark:text-slate-600" />
            </div>
          ))}

          {runs.length > 5 && (
            <div className="mt-4 flex justify-center border-t border-slate-100 pt-4 dark:border-slate-800">
              <button
                type="button"
                onClick={() => setShowAll(!showAll)}
                className="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800"
              >
                {showAll ? (
                  <>
                    Show Less <ChevronUp className="h-4 w-4" />
                  </>
                ) : (
                  <>
                    Show More ({runs.length - 5} more) <ChevronDown className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      )}
    </section>
  );
}


