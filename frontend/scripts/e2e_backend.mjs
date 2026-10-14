// Starts the real API for e2e tests on a fresh database (demo mode "empty": consent pending,
// no transactions yet), with a fixed token the tests put in localStorage.
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = join(dirname(fileURLToPath(import.meta.url)), '..');
const root = join(frontend, '..');
const dir = join(frontend, '.e2e');
mkdirSync(dir, { recursive: true });
for (const f of ['e2e.db', 'e2e.db-wal', 'e2e.db-shm']) rmSync(join(dir, f), { force: true });

const python =
  process.platform === 'win32'
    ? join(root, '.venv', 'Scripts', 'python.exe')
    : join(root, '.venv', 'bin', 'python');
const child = spawn(
  python,
  [
    '-m',
    'copilot.cli',
    'serve',
    '--db',
    join(dir, 'e2e.db'),
    '--port',
    '8765',
    '--demo',
    'empty',
    '--token',
    'e2e-token',
  ],
  { cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } },
);
child.on('exit', (code) => process.exit(code ?? 0));
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill());
