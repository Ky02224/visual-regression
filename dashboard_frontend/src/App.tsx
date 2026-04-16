import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { Dashboard } from './pages/Dashboard';
import { Actions } from './pages/Actions';
import { Baselines } from './pages/Baselines';
import { Summaries } from './pages/Summaries';
import { ReportAnalysis } from './pages/ReportAnalysis';
import { Projects } from './pages/Projects';
import { Integrations } from './pages/Integrations';
import { Login } from './pages/Login';

import { ThemeProvider } from './components/ThemeProvider';
import { RoleProvider } from './context/RoleContext';

export default function App() {
  return (
    <RoleProvider>
      <ThemeProvider defaultTheme="light" storageKey="vite-ui-theme">
        <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/actions" element={<Actions />} />
            <Route path="/baselines" element={<Baselines />} />
            <Route path="/summaries" element={<Summaries />} />
            <Route path="/integrations" element={<Integrations />} />
            <Route path="/report/:id" element={<ReportAnalysis />} />
            <Route path="/projects" element={<Projects />} />
          </Route>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </BrowserRouter>
      </ThemeProvider>
    </RoleProvider>
  );
}

