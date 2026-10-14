import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

// The API runs on localhost only (see `copilot serve`); the dev server proxies /api to it so the
// browser never needs CORS in development.
const API_TARGET = process.env.FINCO_API_URL ?? 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.FINCO_WEB_PORT ?? 5173),
    strictPort: true,
    proxy: { '/api': { target: API_TARGET, changeOrigin: false } },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./tests/setup.ts'],
    include: ['tests/unit/**/*.test.{ts,tsx}'],
    css: false,
  },
});
