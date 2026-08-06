/**
 * SDK behaviour against a real HTTP server.
 *
 * The SDK had no tests at all, while being the integration path a team is most
 * likely to adopt and the most recently changed part of the system (DOM upload).
 * These run the compiled output against a throwaway node server, so what is
 * asserted is what a consumer installs.
 *
 * Run with: npm test  (builds first — the tests import from dist/)
 */
const { test, describe, before, beforeEach, after } = require('node:test');
const assert = require('node:assert');
const http = require('node:http');

const sdk = require('../dist/index.js');

/** A page double: enough surface for visualSnapshot, no browser. */
function fakePage(overrides = {}) {
  return {
    screenshot: async () => Buffer.from('fake-png-bytes'),
    viewportSize: () => ({ width: 1280, height: 720 }),
    url: () => 'https://example.test/page',
    evaluate: async () => ({ elements: [{ tag: 'DIV', x: 0, y: 0, w: 10, h: 10 }] }),
    ...overrides,
  };
}

/** Start a server whose per-route behaviour each test controls. */
function startServer(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ server, url: `http://127.0.0.1:${port}` });
    });
  });
}

function readBody(req) {
  return new Promise((resolve) => {
    let data = '';
    req.on('data', (c) => { data += c; });
    req.on('end', () => resolve(data));
  });
}

describe('visualSnapshot', () => {
  let ctx;
  const calls = [];

  beforeEach(() => {
    calls.length = 0;
    sdk.__resetDomCaptureCacheForTests();
  });

  after(() => { if (ctx) ctx.server.close(); });

  test('uploads the DOM alongside the screenshot', async () => {
    ctx = await startServer(async (req, res) => {
      calls.push(req.url);
      if (req.url === '/api/sdk/dom-capture-js') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ js: '() => ({elements: []})' }));
        return;
      }
      const body = JSON.parse(await readBody(req));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, action: 'compared', passed: true, _dom: !!body.dom }));
    });

    const result = await sdk.visualSnapshot(fakePage(), 'home', { serverUrl: ctx.url });

    assert.equal(result.ok, true);
    assert.equal(result._dom, true, 'the payload reached the server without its dom field');
    assert.ok(calls.includes('/api/sdk/dom-capture-js'));
    ctx.server.close();
  });

  test('still uploads the screenshot when the DOM script cannot be fetched', async () => {
    ctx = await startServer(async (req, res) => {
      if (req.url === '/api/sdk/dom-capture-js') {
        res.writeHead(403, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ detail: 'Forbidden' }));
        return;
      }
      const body = JSON.parse(await readBody(req));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, action: 'compared', _dom: !!body.dom }));
    });

    const result = await sdk.visualSnapshot(fakePage(), 'home', { serverUrl: ctx.url });

    assert.equal(result.ok, true, 'a missing DOM script must not fail the snapshot');
    assert.equal(result._dom, false);
    ctx.server.close();
  });

  test('a transient DOM-script failure does not disable capture for the rest of the run', async () => {
    // The regression: any response without a "js" key latched null for the
    // lifetime of the process, so one early 403 — before the API key was
    // configured, say — silently downgraded every later snapshot to pixels
    // only, with the run still green and nothing reporting it.
    let served = 0;
    ctx = await startServer(async (req, res) => {
      if (req.url === '/api/sdk/dom-capture-js') {
        served += 1;
        if (served === 1) {
          res.writeHead(503, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ detail: 'starting up' }));
          return;
        }
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ js: '() => ({elements: []})' }));
        return;
      }
      const body = JSON.parse(await readBody(req));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, action: 'compared', _dom: !!body.dom }));
    });

    const first = await sdk.visualSnapshot(fakePage(), 'a', { serverUrl: ctx.url });
    const second = await sdk.visualSnapshot(fakePage(), 'b', { serverUrl: ctx.url });

    assert.equal(first._dom, false, 'first snapshot has no DOM, as expected');
    assert.equal(second._dom, true, 'capture stayed disabled after a transient failure');
    ctx.server.close();
  });

  test('a server that answers without a script is only asked once', async () => {
    let served = 0;
    ctx = await startServer(async (req, res) => {
      if (req.url === '/api/sdk/dom-capture-js') {
        served += 1;
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({}));   // 2xx, genuinely no script
        return;
      }
      await readBody(req);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, action: 'compared' }));
    });

    await sdk.visualSnapshot(fakePage(), 'a', { serverUrl: ctx.url });
    await sdk.visualSnapshot(fakePage(), 'b', { serverUrl: ctx.url });

    assert.equal(served, 1, 'a settled negative should be cached, not re-fetched per snapshot');
    ctx.server.close();
  });

  test('sends the documented defaults', async () => {
    let body;
    ctx = await startServer(async (req, res) => {
      if (req.url === '/api/sdk/dom-capture-js') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({}));
        return;
      }
      body = JSON.parse(await readBody(req));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, action: 'compared' }));
    });

    await sdk.visualSnapshot(fakePage(), 'home', { serverUrl: ctx.url });

    // hybrid, matching every other entry point: 'ai' would let the model alone
    // decide pass/fail.
    assert.equal(body.comparison_mode, 'hybrid');
    assert.equal(body.threshold_pct, 0.5);
    assert.equal(body.pixel_threshold, 20);
    assert.equal(body.min_region_area, 120);
    assert.equal(body.viewport_width, 1280);
    assert.equal(body.name, 'home');
    ctx.server.close();
  });

  test('forwards the API key as X-Access-Key', async () => {
    let header;
    ctx = await startServer(async (req, res) => {
      header = req.headers['x-access-key'];
      if (req.url === '/api/sdk/dom-capture-js') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({}));
        return;
      }
      await readBody(req);
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, action: 'compared' }));
    });

    await sdk.visualSnapshot(fakePage(), 'home', { serverUrl: ctx.url, apiKey: 'secret-key' });

    assert.equal(header, 'secret-key');
    ctx.server.close();
  });

  test('an unresponsive server fails the snapshot instead of hanging', async () => {
    // node's http.request has no default timeout, so a server that accepts the
    // socket and never answers left the awaited promise pending forever and
    // hung the caller's whole test run.
    ctx = await startServer(() => { /* accept, never respond */ });
    process.env.VR_TIMEOUT_MS = '400';

    const started = Date.now();
    const result = await sdk.visualSnapshot(fakePage(), 'home', { serverUrl: ctx.url });
    const elapsed = Date.now() - started;

    delete process.env.VR_TIMEOUT_MS;
    assert.equal(result.ok, false);
    assert.match(String(result.error), /Timed out/);
    assert.ok(elapsed < 8000, `took ${elapsed}ms — the timeout did not fire`);
    ctx.server.close();
  });

  test('a page that refuses to evaluate still produces a snapshot', async () => {
    ctx = await startServer(async (req, res) => {
      if (req.url === '/api/sdk/dom-capture-js') {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ js: '() => ({})' }));
        return;
      }
      const body = JSON.parse(await readBody(req));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ ok: true, action: 'compared', _dom: !!body.dom }));
    });

    const page = fakePage({
      evaluate: async () => { throw new Error('CSP blocked evaluation'); },
    });
    const result = await sdk.visualSnapshot(page, 'home', { serverUrl: ctx.url });

    assert.equal(result.ok, true);
    assert.equal(result._dom, false);
    ctx.server.close();
  });
});
