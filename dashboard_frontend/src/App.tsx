import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Layout } from './components/Layout';

// Route-level code splitting: each page only downloads when its route is
// visited, instead of every page's code shipping in the initial bundle.
const Dashboard = React.lazy(() => import('./pages/Dashboard').then(m => ({ default: m.Dashboard })));
const Actions = React.lazy(() => import('./pages/Actions').then(m => ({ default: m.Actions })));
const Baselines = React.lazy(() => import('./pages/Baselines').then(m => ({ default: m.Baselines })));
const Summaries = React.lazy(() => import('./pages/Summaries').then(m => ({ default: m.Summaries })));
const ReportAnalysis = React.lazy(() => import('./pages/ReportAnalysis').then(m => ({ default: m.ReportAnalysis })));
const Integrations = React.lazy(() => import('./pages/Integrations').then(m => ({ default: m.Integrations })));
const SuiteResults = React.lazy(() => import('./pages/SuiteResults').then(m => ({ default: m.SuiteResults })));
const BuildDetail = React.lazy(() => import('./pages/BuildDetail').then(m => ({ default: m.BuildDetail })));
const Login = React.lazy(() => import('./pages/Login').then(m => ({ default: m.Login })));
const UserManagement = React.lazy(() => import('./pages/UserManagement').then(m => ({ default: m.UserManagement })));

import { ThemeProvider } from './components/ThemeProvider';
import { RoleProvider, useRole } from './context/RoleContext';

function RouteLoading() {
  return (
    <div className="h-screen flex items-center justify-center bg-[var(--surface)]">
      <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, { hasError: boolean, error: Error | null }> {
  constructor(props: any) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }
  componentDidCatch(error: Error, errorInfo: any) {
    console.error("ErrorBoundary caught an error", error, errorInfo);
  }
  render() {
    if (this.state.hasError) {
      return (
        <div className="h-screen flex flex-col items-center justify-center gap-4 bg-[var(--surface)] p-6 text-center">
          <h1 className="text-2xl font-bold text-red-600">Something went wrong</h1>
          <p className="text-sm text-[var(--on-surface-variant)] max-w-md">{this.state.error?.message}</p>
          <button onClick={() => window.location.reload()} className="px-4 py-2 bg-primary text-white rounded-md font-semibold text-sm">
            Reload Page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { authenticated, loading } = useRole();
  const location = useLocation();
  if (loading) return (
    <div className="h-screen flex items-center justify-center bg-[var(--surface)]">
      <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
  if (!authenticated) return <Navigate to="/login" state={{ from: location }} replace />;
  return <>{children}</>;
}

function NotFound() {
  return (
    <div className="h-screen flex flex-col items-center justify-center gap-4 bg-[var(--surface)]">
      <h1 className="text-4xl font-bold text-[var(--on-surface)]">404</h1>
      <p className="text-[var(--on-surface-variant)]">Page not found</p>
      <a href="/" className="text-primary underline">Go to Dashboard</a>
    </div>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <RoleProvider>
        <ThemeProvider defaultTheme="light" storageKey="visual-regression-theme">
          <BrowserRouter>
            <React.Suspense fallback={<RouteLoading />}>
              <Routes>
                <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/actions" element={<Actions />} />
                  <Route path="/baselines" element={<Baselines />} />
                  <Route path="/summaries" element={<Summaries />} />
                  <Route path="/integrations" element={<Integrations />} />
                  <Route path="/report/:id" element={<ReportAnalysis />} />
                  <Route path="/suite/:suiteName" element={<SuiteResults />} />
                  <Route path="/build/:buildId" element={<BuildDetail />} />
                  <Route path="/users" element={<UserManagement />} />
                </Route>
                <Route path="/login" element={<Login />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </React.Suspense>
          </BrowserRouter>
        </ThemeProvider>
      </RoleProvider>
    </ErrorBoundary>
  );
}
