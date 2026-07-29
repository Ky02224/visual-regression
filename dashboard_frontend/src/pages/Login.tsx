import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Layers } from 'lucide-react';
import { useRole } from '../context/RoleContext';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';

export function Login() {
  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const { login, authenticated } = useRole();

  // ProtectedRoute attaches the page a logged-out user was trying to reach
  // as router state before bouncing them here — send them back to it
  // instead of always landing on the Dashboard.
  const from = (location.state as { from?: { pathname: string } } | null)?.from?.pathname || '/';

  React.useEffect(() => {
    if (authenticated) navigate(from, { replace: true });
  }, [authenticated, navigate, from]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    const result = await login(email, password);
    setSubmitting(false);
    if (!result.ok) { setError(result.error || 'Login failed'); return; }
    navigate(from, { replace: true });
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-gradient-to-b from-stone-50 to-stone-100 dark:from-zinc-900 dark:to-zinc-950">
      <div className="w-full max-w-md panel p-8 shadow-sm">
        <div className="flex flex-col items-center text-center mb-8">
          <div className="w-11 h-11 rounded-md bg-indigo-600 flex items-center justify-center text-white mb-4"><Layers className="w-6 h-6" /></div>
          <h1 className="text-xl font-semibold text-[var(--on-surface)]">The Lens</h1>
          <p className="text-sm text-[var(--on-surface-variant)] mt-1">Catch visual changes before deploy</p>
        </div>
        <h2 className="text-lg font-semibold mb-1">Sign in</h2>
        <p className="text-sm text-[var(--on-surface-variant)] mb-6">Enter your credentials to continue</p>
        <form className="space-y-4" onSubmit={onSubmit}>
          <Input label="Username" type="text" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="admin" autoComplete="username" />
          <Input label="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password" />
          {error && <div className="rounded-md border border-red-200 bg-red-50 dark:bg-red-950/30 dark:border-red-900 px-3 py-2 text-sm text-red-700 dark:text-red-400">{error}</div>}
          <Button type="submit" variant="primary" size="lg" className="w-full" disabled={submitting}>{submitting ? 'Signing in…' : 'Sign in'}</Button>
        </form>
        <p className="text-center mt-6 text-xs text-[var(--on-surface-variant)]">Need access? Contact your administrator.</p>
      </div>
    </div>
  );
}
