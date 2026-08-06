import type { Page } from '@playwright/test';
import * as https from 'https';
import * as http from 'http';
import { URL } from 'url';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface VisualSnapshotOptions {
  /**
   * Full URL of your Visual Regression Workbench dashboard server.
   * Defaults to the VR_SERVER_URL environment variable, or 'http://localhost:8130'.
   */
  serverUrl?: string;

  /**
   * API key for authentication. Corresponds to the key shown in the
   * Integrations page of your dashboard.
   * Defaults to the VR_API_KEY environment variable.
   */
  apiKey?: string;

  /**
   * Threshold percentage for this snapshot. Defaults to 0.5.
   */
  thresholdPct?: number;

  /**
   * Pixel colour difference threshold (0–255). Defaults to 20.
   */
  pixelThreshold?: number;

  /**
   * Minimum contiguous changed area in pixels before it counts as a region.
   * Defaults to 120.
   */
  minRegionArea?: number;

  /**
   * How pass/fail is decided. Defaults to 'hybrid'.
   *
   * - 'hybrid'  — a change must clear the pixel threshold *and* be judged
   *               meaningful. The default everywhere else in the system.
   * - 'pixel'   — threshold only; deterministic, and the choice when a run
   *               has to be reproducible or the model is not trusted yet.
   * - 'ai'      — the model alone decides and the pixel signal is discarded.
   *
   * The previous union advertised 'strict' and 'threshold', which the server
   * has never accepted: decision.py takes pixel/ai/hybrid and raises on
   * anything else, so either value failed the request outright.
   */
  comparisonMode?: 'pixel' | 'ai' | 'hybrid';

  /**
   * Capture full-page screenshot. Defaults to true.
   */
  fullPage?: boolean;

  /**
   * Arbitrary suite / build name to tag this snapshot with.
   */
  suiteName?: string;
}

export interface SnapshotResult {
  ok: boolean;
  action: 'baseline_created' | 'compared';
  passed?: boolean;
  runId?: string;
  mismatchPct?: number;
  diffPixels?: number;
  regions?: number;
  aiLabel?: string;
  severity?: string;
  reportUrl?: string;
  exportUrl?: string;
  message?: string;
  error?: string;
}

// ---------------------------------------------------------------------------
// Core helper — POST JSON to the server
// ---------------------------------------------------------------------------

/**
 * How long to wait on the dashboard before giving up, in milliseconds.
 *
 * node's http.request has no default timeout: a server that accepts the socket
 * and then never answers leaves the promise pending forever, and since every
 * snapshot is awaited, one unresponsive server hangs the whole test run with no
 * error to explain it. Override with VR_TIMEOUT_MS.
 */
const DEFAULT_TIMEOUT_MS = 30_000;

function requestTimeoutMs(): number {
  const raw = Number(process.env['VR_TIMEOUT_MS']);
  return Number.isFinite(raw) && raw > 0 ? raw : DEFAULT_TIMEOUT_MS;
}

function postJson(serverUrl: string, path: string, apiKey: string | undefined, body: Record<string, unknown>): Promise<SnapshotResult> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(path, serverUrl);
    const bodyStr = JSON.stringify(body);
    const options: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(bodyStr),
        ...(apiKey ? { 'X-Access-Key': apiKey } : {}),
      },
      timeout: requestTimeoutMs(),
    };

    const lib = parsed.protocol === 'https:' ? https : http;
    const req = lib.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          resolve(JSON.parse(data) as SnapshotResult);
        } catch {
          reject(new Error(`Invalid JSON from server: ${data}`));
        }
      });
    });

    // 'timeout' only fires the event; the socket stays open unless it is
    // destroyed, and without that the promise never settles.
    req.on('timeout', () => {
      req.destroy(new Error(`Timed out after ${requestTimeoutMs()}ms waiting for ${serverUrl}`));
    });
    req.on('error', reject);
    req.write(bodyStr);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// DOM capture
// ---------------------------------------------------------------------------

/**
 * The capture script is fetched from the server rather than duplicated here.
 *
 * Structural comparison is what separates this server from a pixel differ, and
 * it needs element data from both sides. Uploading only a screenshot leaves the
 * DOM diff nothing to compare and the model's structural features all zero.
 * Since the SDK already holds a Playwright Page, the DOM is one evaluate() away.
 *
 * Keeping the script server-side means a field added to the capture reaches
 * clients without an SDK release, and the two can never disagree about the
 * shape of a snapshot.
 */
let domCaptureScript: string | null | undefined;

/**
 * Clear the cached DOM-capture script. Test-only.
 *
 * The cache is deliberately process-wide — the script is fetched once per run —
 * which is exactly what makes its states hard to assert on without a way to
 * return to the initial one.
 *
 * @internal
 */
export function __resetDomCaptureCacheForTests(): void {
  domCaptureScript = undefined;
}

function getJson(serverUrl: string, path: string, apiKey: string | undefined): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(path, serverUrl);
    const lib = parsed.protocol === 'https:' ? https : http;
    const req = lib.request(
      {
        hostname: parsed.hostname,
        port: parsed.port || (parsed.protocol === 'https:' ? 443 : 80),
        path: parsed.pathname + parsed.search,
        method: 'GET',
        headers: { ...(apiKey ? { 'X-Access-Key': apiKey } : {}) },
        timeout: requestTimeoutMs(),
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(`GET ${path} returned ${res.statusCode}`));
            return;
          }
          try {
            resolve(JSON.parse(data) as Record<string, unknown>);
          } catch {
            reject(new Error(`Invalid JSON from server: ${data}`));
          }
        });
      },
    );
    req.on('timeout', () => {
      req.destroy(new Error(`Timed out after ${requestTimeoutMs()}ms waiting for ${serverUrl}`));
    });
    req.on('error', reject);
    req.end();
  });
}

async function captureDom(
  page: Page, serverUrl: string, apiKey: string | undefined,
): Promise<unknown | undefined> {
  // A server too old to serve the script, or a page that refuses to evaluate
  // it, must not fail the snapshot: structural analysis is an enhancement, and
  // the screenshot comparison still stands without it.
  try {
    if (domCaptureScript === undefined) {
      const payload = await getJson(serverUrl, '/api/sdk/dom-capture-js', apiKey);
      const js = payload['js'];
      if (typeof js === 'string' && js.length > 0) {
        domCaptureScript = js;
      } else {
        // Reached only when the server answered 2xx and genuinely carried no
        // script — a property of that server, so it is safe to latch for the
        // run. Everything else now rejects in getJson (4xx/5xx are checked
        // there) and lands in the catch below with the cache still unset.
        //
        // That split is the point: previously any response without a "js" key —
        // including the error body of a 403 returned before the API key was
        // configured — latched `null` for the lifetime of the process, and
        // every later snapshot uploaded pixels only. The run still passed, so
        // nothing anywhere reported that structural comparison had been off.
        domCaptureScript = null;
      }
    }
    if (!domCaptureScript) return undefined;
    return await page.evaluate(domCaptureScript);
  } catch {
    // Thrown before any assignment above, so the script stays `undefined` and
    // the next snapshot tries again.
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// Main export: visualSnapshot()
// ---------------------------------------------------------------------------

/**
 * Capture a visual snapshot and send it to your Visual Regression Workbench.
 *
 * @example
 * ```typescript
 * import { test } from '@playwright/test';
 * import { visualSnapshot } from 'visual-regression-playwright';
 *
 * test('homepage looks correct', async ({ page }) => {
 *   await page.goto('https://example.com');
 *   await visualSnapshot(page, 'homepage');
 * });
 * ```
 *
 * On first run, the image becomes the baseline.
 * On subsequent runs, it is compared against the baseline.
 * Set VR_SERVER_URL and VR_API_KEY environment variables to configure.
 */
export async function visualSnapshot(
  page: Page,
  name: string,
  options: VisualSnapshotOptions = {}
): Promise<SnapshotResult> {
  const serverUrl = options.serverUrl ?? process.env['VR_SERVER_URL'] ?? 'http://localhost:8130';
  const apiKey = options.apiKey ?? process.env['VR_API_KEY'];

  // Take the screenshot
  const screenshotBuffer = await page.screenshot({
    fullPage: options.fullPage ?? true,
    type: 'png',
  });

  const imageBase64 = screenshotBuffer.toString('base64');
  const viewportSize = page.viewportSize();
  const currentUrl = page.url();
  const dom = await captureDom(page, serverUrl, apiKey);

  const payload: Record<string, unknown> = {
    name,
    image: imageBase64,
    url: currentUrl,
    viewport_width: viewportSize?.width ?? 1440,
    viewport_height: viewportSize?.height ?? 900,
    browser: 'playwright-sdk',
    threshold_pct: options.thresholdPct ?? 0.5,
    pixel_threshold: options.pixelThreshold ?? 20,
    min_region_area: options.minRegionArea ?? 120,
    // "hybrid", matching the CLI, the dashboard and the suite runner. "ai"
    // discards the pixel signal entirely and lets the model alone decide
    // pass/fail — the least safe default anywhere, and worst of all here,
    // where an upload historically carried no structural evidence either.
    comparison_mode: options.comparisonMode ?? 'hybrid',
    suite_name: options.suiteName ?? null,
  };
  if (dom) payload['dom'] = dom;

  try {
    const result = await postJson(serverUrl, '/api/sdk/snapshot', apiKey, payload);

    if (!result.ok) {
      console.error(`[VR Workbench] Snapshot '${name}' failed: ${result.error}`);
    } else if (result.action === 'baseline_created') {
      console.log(`[VR Workbench] ✓ Baseline created for '${name}'`);
    } else {
      const status = result.passed ? '✓ PASS' : '✗ FAIL';
      const mismatch = result.mismatchPct?.toFixed(2) ?? '?';
      console.log(`[VR Workbench] ${status} '${name}' — ${mismatch}% mismatch${result.reportUrl ? ` — ${serverUrl}${result.reportUrl}` : ''}`);
    }

    return result;
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`[VR Workbench] Failed to connect to server at ${serverUrl}: ${message}`);
    return { ok: false, action: 'compared', error: message };
  }
}

/**
 * Playwright fixture-based helper for use with @playwright/test.
 *
 * @example
 * ```typescript
 * // playwright.config.ts
 * import { createVisualFixtures } from 'visual-regression-playwright';
 * const { test, expect } = createVisualFixtures();
 * export { test, expect };
 *
 * // my.spec.ts
 * import { test } from './playwright.config';
 * test('my page', async ({ page, snapshot }) => {
 *   await page.goto('/');
 *   await snapshot('home');
 * });
 * ```
 */
export function createVisualFixtures(defaults: VisualSnapshotOptions = {}) {
  // Lazy import to avoid pulling in @playwright/test at module-load time
  // so the file can also be used in non-test contexts.
  // The `as typeof import(...)` is what makes this compile: a bare require()
  // returns `any`, and TypeScript rejects type arguments on an untyped call, so
  // `base.extend<{ snapshot: ... }>` below failed with TS2347. The cast is
  // erased at compile time, so the import stays lazy.
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const { test: base } = require('@playwright/test') as typeof import('@playwright/test');

  return base.extend<{ snapshot: (name: string, opts?: VisualSnapshotOptions) => Promise<SnapshotResult> }>({
    snapshot: async ({ page }: { page: Page }, use: (fn: (name: string, opts?: VisualSnapshotOptions) => Promise<SnapshotResult>) => Promise<void>) => {
      await use((name: string, opts: VisualSnapshotOptions = {}) =>
        visualSnapshot(page, name, { ...defaults, ...opts })
      );
    },
  });
}
