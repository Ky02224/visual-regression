import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import { Actions } from './pages/Actions';
import { Baselines } from './pages/Baselines';
import { Summaries } from './pages/Summaries';
import { ReportAnalysis } from './pages/ReportAnalysis';
import { Integrations } from './pages/Integrations';
import { SuiteResults } from './pages/SuiteResults';
import { BuildDetail } from './pages/BuildDetail';
import { Login } from './pages/Login';
import { UserManagement } from './pages/UserManagement';

import { ThemeProvider } from './components/ThemeProvider';
import { RoleProvider, useRole } from './context/RoleContext';

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { authenticated, loading } = useRole();
  if (loading) return null;
  if (!authenticated) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <RoleProvider>
      <ThemeProvider defaultTheme="light" storageKey="vite-ui-theme">
        <BrowserRouter>
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
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </RoleProvider>
  );
}
