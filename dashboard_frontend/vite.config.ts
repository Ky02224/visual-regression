import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '.', '');
  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modify — file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8130',
          changeOrigin: true,
        },
        '/artifacts': {
          target: 'http://127.0.0.1:8130',
          changeOrigin: true,
        },
        '/baseline': {
          target: 'http://127.0.0.1:8130',
          changeOrigin: true,
        },
      },
    },
    build: {
      // No manualChunks. Splitting vendors by substring broke the production
      // build outright: `id.includes('react')` sent react and react-dom to
      // vendor.react while scheduler and motion — neither has "react" in its
      // path — stayed in vendor, even though both sides import each other.
      // That circular chunk dependency let vendor evaluate before React's
      // bindings were live, so motion hit `undefined.createContext` and the
      // app rendered nothing at all. (The react-router branch was also dead:
      // the react check above it matched react-router first.)
      // Rollup's default chunking derives order from the real import graph
      // and does not have this failure mode.
      chunkSizeWarningLimit: 600,
    },
  };
});
