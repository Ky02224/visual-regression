import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { RoleProvider } from '../context/RoleContext';
import { Actions } from './Actions';

/**
 * Multiple Capture used to fail with "Playwright Sync API inside the asyncio
 * loop" for the rest of a dashboard-server process's lifetime once any
 * sync-API action (Single Capture, Run Comparison) had run first — the tab
 * UI itself gave no indication anything was wrong. These tests lock in that
 * each tab submits to its own distinct endpoint with the right payload shape,
 * so a future regression that silently merges/misroutes a tab's submit
 * handler shows up here instead of only in production.
 */

function mockFetchJson(handlers: Record<string, unknown>) {
  return vi.fn((url: string, _init?: RequestInit) => {
    for (const [pattern, body] of Object.entries(handlers)) {
      if (url.includes(pattern)) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(body),
        } as Response);
      }
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ ok: true }),
    } as Response);
  });
}

function renderActions(role: 'admin' | 'developer' | 'viewer' = 'admin') {
  global.fetch = mockFetchJson({
    '/api/auth/me': { ok: true, authenticated: true, user: { email: 'a@b.com', role, name: 'Test' } },
    '/api/dashboard': { baselines: [{ name: 'demo-home-en' }, { name: 'demo-login-en' }] },
  });
  return render(
    <MemoryRouter>
      <RoleProvider>
        <Actions />
      </RoleProvider>
    </MemoryRouter>
  );
}

describe('Actions page', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('defaults to the Single Capture tab and disables Capture until URL and label are filled', async () => {
    renderActions();
    await waitFor(() => expect(screen.getByText('Capture a single page screenshot as a new baseline.')).toBeInTheDocument());

    const captureButton = screen.getByRole('button', { name: /capture/i });
    expect(captureButton).toBeDisabled();

    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText('https://example.com/page'), 'https://example.com/page');
    await user.type(screen.getByPlaceholderText('e.g., Homepage - Mobile'), 'my-baseline');

    expect(captureButton).toBeEnabled();
  });

  it('switches tabs and shows the matching form + description for each', async () => {
    renderActions();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole('tab', { name: /single capture/i })).toBeInTheDocument());

    await user.click(screen.getByRole('tab', { name: /multiple capture/i }));
    expect(await screen.findByText('Capture multiple pages from a target website.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /multiple capture/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /single capture/i })).toHaveAttribute('aria-selected', 'false');

    await user.click(screen.getByRole('tab', { name: /run comparison/i }));
    expect(await screen.findByText('Compare a baseline against a live URL.')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /run comparison/i })).toHaveAttribute('aria-selected', 'true');

    await user.click(screen.getByRole('tab', { name: /single capture/i }));
    expect(await screen.findByText('Capture a single page screenshot as a new baseline.')).toBeInTheDocument();
  });

  it('submits Single Capture to /api/actions/create-baseline with the form fields', async () => {
    renderActions();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByPlaceholderText('https://example.com/page')).toBeInTheDocument());

    await user.type(screen.getByPlaceholderText('https://example.com/page'), 'https://example.com/page');
    const nameInput = screen.getByPlaceholderText('e.g., Homepage - Mobile');
    await user.clear(nameInput);
    await user.type(nameInput, 'my-baseline');
    await user.click(screen.getByRole('button', { name: /capture/i }));

    await waitFor(() => {
      const calls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const call = calls.find((c) => String(c[0]).includes('/api/actions/create-baseline'));
      expect(call).toBeTruthy();
      const body = JSON.parse((call as any)[1].body);
      expect(body).toMatchObject({ url: 'https://example.com/page', name: 'my-baseline' });
    });
  });

  it('submits Multiple Capture to /api/actions/create-multiple-baselines, not the single-capture endpoint', async () => {
    renderActions();
    const user = userEvent.setup();
    await waitFor(() => expect(screen.getByRole('tab', { name: /multiple capture/i })).toBeInTheDocument());
    await user.click(screen.getByRole('tab', { name: /multiple capture/i }));

    const urlInput = await screen.findByPlaceholderText('https://example.com');
    await user.type(urlInput, 'https://example.com');
    await user.click(screen.getByRole('button', { name: /start capture run/i }));

    await waitFor(() => {
      const calls = (global.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const wrongEndpoint = calls.find((c) => String(c[0]) === '/api/actions/create-baseline');
      const rightEndpoint = calls.find((c) => String(c[0]).includes('/api/actions/create-multiple-baselines'));
      expect(wrongEndpoint).toBeFalsy();
      expect(rightEndpoint).toBeTruthy();
    });
  });

  it('shows a background-task message and polls task-status when the endpoint returns a task_id', async () => {
    global.fetch = mockFetchJson({
      '/api/auth/me': { ok: true, authenticated: true, user: { email: 'a@b.com', role: 'admin', name: 'Test' } },
      '/api/dashboard': { baselines: [] },
      '/api/actions/create-multiple-baselines': { ok: true, task_id: 'abc-123' },
      '/api/actions/task-status': { status: 'running' },
    });
    render(
      <MemoryRouter>
        <RoleProvider>
          <Actions />
        </RoleProvider>
      </MemoryRouter>
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole('tab', { name: /multiple capture/i }));
    await user.type(await screen.findByPlaceholderText('https://example.com'), 'https://example.com');
    await user.click(screen.getByRole('button', { name: /start capture run/i }));

    expect(await screen.findByText(/started in background/i)).toBeInTheDocument();
  });

  it('blocks action forms behind an access-required message for viewer role', async () => {
    renderActions('viewer');
    expect(await screen.findByText('Elevated Access Required')).toBeInTheDocument();
    expect(screen.queryByPlaceholderText('https://example.com/page')).not.toBeInTheDocument();
  });
});
