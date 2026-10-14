// One command for the demo: fresh demo database, real API on 127.0.0.1:8765, the web app on
// 127.0.0.1:5173, and the exact URL to open (the session token rides in the URL fragment, which
// the app stores and removes, so it never reaches a server log).
//
//   npm run demo             start empty: connect, import and categorise live in front of people
//   npm run demo:imported    start with the statements already imported
//   npm run demo -- --keep   keep the existing demo database instead of resetting it
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = join(dirname(fileURLToPath(import.meta.url)), '..');
const root = join(frontend, '..');
const dir = join(frontend, '.demo');
const imported = process.argv.includes('--imported');
const keep = process.argv.includes('--keep');
const TOKEN = 'demo';

mkdirSync(dir, { recursive: true });
if (!keep)
  for (const f of ['demo.db', 'demo.db-wal', 'demo.db-shm']) rmSync(join(dir, f), { force: true });

const python =
  process.platform === 'win32'
    ? join(root, '.venv', 'Scripts', 'python.exe')
    : join(root, '.venv', 'bin', 'python');
const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };

const api = spawn(
  python,
  [
    '-m',
    'copilot.cli',
    'serve',
    '--db',
    join(dir, 'demo.db'),
    '--port',
    '8765',
    '--demo',
    imported ? 'imported' : 'empty',
    '--token',
    TOKEN,
  ],
  { cwd: root, stdio: 'inherit', env },
);
const vite = spawn(
  process.execPath,
  [join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1'],
  {
    cwd: frontend,
    stdio: 'inherit',
    env,
  },
);

setTimeout(() => {
  console.log('\n  FinCo demo is running. Open:\n');
  console.log(`    http://127.0.0.1:5173/welcome#token=${TOKEN}\n`);
  console.log('  Press Ctrl+C to stop both servers.\n');
}, 6000);

const stop = () => {
  api.kill();
  vite.kill();
  process.exit(0);
};
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, stop);
api.on('exit', (code) => {
  if (code) {
    console.error(`API exited with code ${code}`);
    stop();
  }
});
