import { defineConfig, devices } from '@playwright/test';

// Separate ports from `npm run demo` (8765 and 5173) so tests never collide with a live demo.
const API_PORT = process.env.E2E_API_PORT ?? '8775';
const WEB_PORT = process.env.E2E_WEB_PORT ?? '5183';

export default defineConfig({
  testDir: 'tests/e2e',
  timeout: 90_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: 'node scripts/e2e_backend.mjs',
      env: { E2E_API_PORT: API_PORT, FINCO_LLM: 'off' },
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { FINCO_WEB_PORT: WEB_PORT, FINCO_API_URL: `http://127.0.0.1:${API_PORT}` },
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
  projects: [
    { name: 'demo', testMatch: /demo\.spec\.ts/ },
    { name: 'shots', testMatch: /shots\.spec\.ts/, dependencies: ['demo'] },
  ],
});
