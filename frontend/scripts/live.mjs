// Live mode launcher: the same app on your real data, on its own ports and database.
//
//   npm run live
//
// Starts the live API (port 8200, frontend/.demo/live.db, real clock) and the web app on port
// 5273 pointed at it. The demo (npm run demo, ports 8765 and 5173) is a different pair of
// processes and a different database, and keeps working side by side.
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = join(dirname(fileURLToPath(import.meta.url)), '..');
const root = join(frontend, '..');
const dir = join(frontend, '.demo');
mkdirSync(dir, { recursive: true });

const API_PORT = process.env.LIVE_PORT ?? '8200';
const WEB_PORT = process.env.LIVE_WEB_PORT ?? '5273';
const TOKEN = process.env.LIVE_TOKEN ?? randomBytes(12).toString('base64url');
const lan = process.argv.includes('--lan'); // let a phone on the same Wi-Fi reach the webhook
const withModel = process.argv.includes('--llm');

const python =
  process.platform === 'win32'
    ? join(root, '.venv', 'Scripts', 'python.exe')
    : join(root, '.venv', 'bin', 'python');
const env = { ...process.env, PYTHONIOENCODING: 'utf-8', LIVE_TOKEN: TOKEN, LIVE_PORT: API_PORT };
if (lan) env.LIVE_LAN = '1';

const api = spawn(python, ['-m', 'copilot.live', ...(withModel ? ['--llm'] : [])], {
  cwd: root,
  stdio: 'inherit',
  env,
});
const vite = spawn(
  process.execPath,
  [join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1'],
  {
    cwd: frontend,
    stdio: 'inherit',
    env: {
      ...env,
      FINCO_WEB_PORT: WEB_PORT,
      FINCO_API_URL: `http://127.0.0.1:${API_PORT}`,
    },
  },
);

setTimeout(() => {
  console.log('\n  FinCo LIVE is running on your real data. Open:\n');
  console.log(`    http://127.0.0.1:${WEB_PORT}/welcome#token=${TOKEN}\n`);
  console.log('  Then: Live data > import your statement CSV. Ctrl+C stops both servers.\n');
}, 6000);

const stop = () => {
  api.kill();
  vite.kill();
  process.exit(0);
};
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, stop);
api.on('exit', (code) => {
  if (code) {
    console.error(`Live API exited with code ${code}`);
    stop();
  }
});
