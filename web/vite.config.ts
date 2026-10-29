import { fileURLToPath, URL } from 'node:url';
import { lingui } from '@lingui/vite-plugin';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import mkcert from 'vite-plugin-mkcert';

/**
 * The two APIs this app talks to, proxied in development the way
 * docker/Caddyfile routes them in production, so the browser sees same-origin
 * requests: since 20 July 2026 Telegram only allows Mini App API calls from
 * the app's own origin, and matching that locally keeps the dev environment
 * honest.
 *
 * `/api/v1/*` is the catalog's API (`catalog/`). Local by default, on
 * 8010 because something else on the development machine holds 8000; set
 * CATALOG_ORIGIN to use a deployed one instead. Everything else under `/api`
 * is this repository's webapi.
 */
const CATALOG_TARGET = process.env.CATALOG_ORIGIN || 'http://127.0.0.1:8010';
const WEBAPI_TARGET = 'http://127.0.0.1:8787';

/**
 * Escape hatch for environments where mkcert cannot install its CA.
 *
 * The first run of mkcert needs `sudo` to write into the system trust store,
 * which is impossible in CI and awkward on a locked-down machine. Set
 * `VITE_NO_HTTPS=1` to serve over plain HTTP: enough to work on components in a
 * desktop browser, but Telegram will refuse to load the app, so it is not a way
 * to test inside the client.
 */
const httpsDisabled = process.env.VITE_NO_HTTPS === '1';

export default defineConfig({
  plugins: [
    react(),
    // Compiles src/locales/*/messages.po into loadable JS modules, and expands
    // the Lingui macros itself: @vitejs/plugin-react v6 no longer runs Babel.
    lingui({ macroTransform: true }),
    // Telegram refuses to load a Mini App over plain HTTP.
    ...(httpsDisabled ? [] : [mkcert()]),
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // Listen on every interface so a phone on the same network can reach it.
    host: true,
    port: 5173,
    // Vite refuses requests whose Host it does not know, which is what stops
    // a hostile page in the browser from talking to the dev server through
    // DNS rebinding. A quick tunnel arrives under a hostname Vite has never
    // seen, so the tunnel's domain is allowed — the domain, not everything.
    allowedHosts: [
      '.trycloudflare.com',
      ...(process.env.VITE_ALLOWED_HOST ? [process.env.VITE_ALLOWED_HOST] : []),
    ],
    proxy: {
      // The more specific prefix first: Vite takes the first match.
      '/api/v1/': { target: CATALOG_TARGET, changeOrigin: true, secure: true },
      '/healthz': { target: CATALOG_TARGET, changeOrigin: true, secure: true },
      '/api': { target: WEBAPI_TARGET, changeOrigin: true },
    },
  },
  preview: {
    host: true,
    port: 5173,
  },
  build: {
    target: 'es2022',
    sourcemap: true,
  },
});
