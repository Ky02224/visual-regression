import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from './apiClient';

// The fetch config used to be built as
// { method, headers: {...merged}, ...options } — spreading `options` LAST
// meant a caller passing options.headers or options.body would silently
// overwrite the carefully-merged Content-Type header or JSON.stringify'd
// body with nothing merged in. No caller does this yet, but it's the one
// shared wrapper for every API call in the app.
describe('apiClient', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    );
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('merges an extra header from options instead of dropping Content-Type', async () => {
    await api.get('/api/thing', { headers: { 'X-Access-Key': 'secret' } });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers).toEqual({
      'Content-Type': 'application/json',
      'X-Access-Key': 'secret',
    });
  });

  it('keeps the JSON.stringify-d body when options is also passed', async () => {
    await api.post('/api/thing', { hello: 'world' }, { headers: { 'X-Access-Key': 'secret' } });

    const [, init] = fetchMock.mock.calls[0];
    expect(init.body).toBe(JSON.stringify({ hello: 'world' }));
    expect(init.method).toBe('POST');
  });

  it('sends credentials: include by default', async () => {
    await api.get('/api/thing');

    const [, init] = fetchMock.mock.calls[0];
    expect(init.credentials).toBe('include');
  });

  it('treats a 204 No Content response as success with no body', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    const result = await api.delete('/api/thing/1');

    expect(result).toBeUndefined();
  });
});
