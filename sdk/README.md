# Visual Regression Playwright SDK

Drop-in replacement for Percy in your Playwright tests. One line of code — your screenshots are automatically compared against your Visual Regression Workbench.

## Quick Start

### 1. Copy the SDK into your project

```bash
# From your test project root, copy the sdk folder
cp -r path/to/visual-regression-workbench/sdk ./vr-sdk
cd vr-sdk && npm install && npm run build
```

### 2. Set environment variables

```bash
# .env or your CI secrets
VR_SERVER_URL=http://localhost:8130   # URL of your dashboard server
VR_API_KEY=tl_live_xxxxxxxxxxxx      # API key from Integrations page
```

### 3. Use in your tests

```typescript
import { test } from '@playwright/test';
import { visualSnapshot } from '../vr-sdk/dist/index';

test('homepage looks correct', async ({ page }) => {
  await page.goto('https://example.com');
  
  // First run → creates baseline automatically
  // Subsequent runs → compares and reports diffs
  await visualSnapshot(page, 'homepage');
});

test('checkout flow', async ({ page }) => {
  await page.goto('https://example.com/checkout');
  await page.fill('#email', 'test@example.com');
  
  await visualSnapshot(page, 'checkout-step-1', {
    thresholdPct: 1.0,          // allow 1% mismatch
    comparisonMode: 'threshold', // skip AI on this one
  });
});
```

### 4. Using the Fixture API (cleaner syntax)

```typescript
// playwright.config.ts
import { createVisualFixtures } from '../vr-sdk/dist/index';
export const { test, expect } = createVisualFixtures({
  serverUrl: process.env.VR_SERVER_URL,
  apiKey: process.env.VR_API_KEY,
});

// my.spec.ts
import { test } from './playwright.config';
test('homepage', async ({ page, snapshot }) => {
  await page.goto('/');
  await snapshot('homepage');
  await page.click('button#open-modal');
  await snapshot('modal-open');
});
```

---

## API Reference

### `visualSnapshot(page, name, options?)`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | `Page` | required | Playwright `Page` object |
| `name` | `string` | required | Unique snapshot name. Used as the baseline key. |
| `options.serverUrl` | `string` | `VR_SERVER_URL` env or `http://localhost:8130` | Dashboard server URL |
| `options.apiKey` | `string` | `VR_API_KEY` env | API key for authentication |
| `options.thresholdPct` | `number` | `0.5` | Max allowed mismatch % before FAIL |
| `options.pixelThreshold` | `number` | `20` | Per-pixel colour delta threshold (0–255) |
| `options.minRegionArea` | `number` | `120` | Min region size in pixels to count |
| `options.comparisonMode` | `'ai'\|'strict'\|'threshold'` | `'ai'` | Comparison strategy |
| `options.fullPage` | `boolean` | `true` | Full-page screenshot |
| `options.suiteName` | `string` | `null` | Tag with a suite/build name |

### `createVisualFixtures(defaults?)`

Returns a Playwright `test` object extended with a `snapshot` fixture.

---

## How It Works

1. `visualSnapshot()` takes a screenshot via Playwright
2. Sends the PNG (base64) to `POST /api/sdk/snapshot` on your dashboard server
3. **First run**: The image is saved as the baseline
4. **Subsequent runs**: The image is compared against the baseline using OpenCV + optional AI
5. Results appear instantly in your dashboard at `http://localhost:8130`

---

## CI Integration

See `.github/workflows/visual-regression-template.yml` in the root of the project for a ready-to-use GitHub Actions workflow.

```yaml
- name: Run visual tests
  run: npx playwright test
  env:
    VR_SERVER_URL: ${{ secrets.VR_SERVER_URL }}
    VR_API_KEY: ${{ secrets.VR_API_KEY }}
```
