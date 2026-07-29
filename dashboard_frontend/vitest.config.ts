import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // ./tests/*.spec.ts are Playwright e2e specs (run via `npm run
    // test:e2e`, a real browser test runner) — vitest's default include
    // pattern matches *.spec.ts too and was picking them up as if they
    // were unit tests, failing immediately since `@playwright/test`'s
    // `test`/`expect` aren't vitest's.
    exclude: ['**/node_modules/**', '**/dist/**', './tests/**'],
  },
});
