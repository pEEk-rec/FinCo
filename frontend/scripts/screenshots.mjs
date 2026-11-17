// Takes the screenshots used in the README and docs, from the real app on a fresh demo database.
//
//   npm run screenshots
//
// It starts its own API (port 8785) and web server (port 5193), so it never disturbs a live demo.
// The story is the demo story: connect the bank, import history, play live payments, then look at
// each screen. Images are written to ../docs/screenshots/.
import { spawn } from 'node:child_process';
import { mkdirSync, rmSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '@playwright/test';

const frontend = join(dirname(fileURLToPath(import.meta.url)), '..');
const root = join(frontend, '..');
const out = join(root, 'docs', 'screenshots');
const work = join(frontend, '.shots-run');
const API_PORT = 8785;
const WEB_PORT = 5193;
const TOKEN = 'shots';
const base = `http://127.0.0.1:${WEB_PORT}`;

mkdirSync(out, { recursive: true });
mkdirSync(work, { recursive: true });
for (const f of ['shots.db', 'shots.db-wal', 'shots.db-shm'])
  rmSync(join(work, f), { force: true });

const python =
  process.platform === 'win32'
    ? join(root, '.venv', 'Scripts', 'python.exe')
    : join(root, '.venv', 'bin', 'python');
const env = {
  ...process.env,
  PYTHONIOENCODING: 'utf-8',
  FINCO_LLM: 'off',
  FINCO_MIN_ASK_PAISE: '100',
};

const api = spawn(
  python,
  [
    '-m',
    'copilot.cli',
    'serve',
    '--db',
    join(work, 'shots.db'),
    '--port',
    String(API_PORT),
    '--demo',
    'empty',
    '--token',
    TOKEN,
    '--real-time',
  ],
  { cwd: root, stdio: 'ignore', env },
);
const vite = spawn(
  process.execPath,
  [join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--host', '127.0.0.1'],
  {
    cwd: frontend,
    stdio: 'ignore',
    env: {
      ...env,
      FINCO_WEB_PORT: String(WEB_PORT),
      FINCO_API_URL: `http://127.0.0.1:${API_PORT}`,
    },
  },
);
const stop = () => {
  api.kill();
  vite.kill();
};
process.on('exit', stop);

async function waitFor(url) {
  for (let i = 0; i < 90; i++) {
    try {
      if ((await fetch(url)).ok) return;
    } catch {
      /* not up yet */
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Timed out waiting for ${url}`);
}

const LAPTOP = { width: 1440, height: 900 };
const PHONE = { width: 390, height: 844 };

try {
  await waitFor(`http://127.0.0.1:${API_PORT}/api/health`);
  await waitFor(base);

  const browser = await chromium.launch();
  const make = async (viewport, mobile) => {
    const ctx = await browser.newContext({
      viewport,
      deviceScaleFactor: mobile ? 2 : 1,
      isMobile: mobile,
      hasTouch: mobile,
    });
    // eslint-disable-next-line no-undef -- runs inside the browser page
    await ctx.addInitScript((t) => window.localStorage.setItem('finco.token', t), TOKEN);
    return { ctx, page: await ctx.newPage() };
  };
  const shot = (page, name) => page.screenshot({ path: join(out, `${name}.png`) });
  const settle = (page, ms = 2200) => page.waitForTimeout(ms);

  // ---- Laptop ---------------------------------------------------------------------------
  const { ctx: lctx, page } = await make(LAPTOP, false);

  await page.goto(`${base}/welcome`);
  await settle(page, 1500);
  await shot(page, '01-welcome');

  await page.goto(`${base}/settings?tab=connections`);
  await page.getByText('Share bank data with FinCo').waitFor();
  await settle(page, 800);
  await shot(page, '02-consent');

  await page.getByRole('button', { name: 'Approve and import' }).click();
  await page
    .getByText(/Categorised by rule: \d+\. By AI: \d+\. Needs you: \d+\./)
    .first()
    .waitFor({ timeout: 90_000 });
  await settle(page, 3500);
  await shot(page, '03-import');

  const feed = page.getByRole('region', { name: 'Live payments' });
  await feed.getByRole('button', { name: 'Send next live payment' }).click();
  await page.getByRole('listitem').filter({ hasText: 'Simulated payment' }).first().waitFor();
  await settle(page, 900);
  await shot(page, '04-live-payment-card');
  // Answer it, then play a payment the app already knows.
  const card = page.getByRole('listitem').filter({ hasText: 'Simulated payment' }).first();
  await card.getByRole('button').first().click();
  await settle(page, 700);
  await feed.getByRole('button', { name: 'Send next live payment' }).click();
  await settle(page, 1200);
  await shot(page, '05-live-payment-quiet');

  const screens = [
    ['06-overview', '/'],
    ['07-transactions', '/transactions'],
    ['08-review', '/review'],
    ['09-plan-budget', '/plan?tab=budget'],
    ['10-plan-goals', '/plan?tab=goals'],
    ['11-settings', '/settings'],
  ];
  for (const [name, path] of screens) {
    await page.goto(`${base}${path}`);
    await settle(page);
    await shot(page, name);
  }

  await page.goto(`${base}/ask`);
  await page.getByRole('textbox').fill('Why did my food spend change this month?');
  await page.keyboard.press('Enter');
  await page.getByTestId('ask-answer').last().waitFor({ timeout: 60_000 });
  await settle(page, 1500);
  await shot(page, '12-ask');
  await lctx.close();

  // ---- Phone ----------------------------------------------------------------------------
  const { ctx: pctx, page: phone } = await make(PHONE, true);
  await phone.goto(`${base}/`);
  await settle(phone);
  await shot(phone, 'phone-1-overview');
  await phone.goto(`${base}/review`);
  await settle(phone);
  await shot(phone, 'phone-2-review');
  await phone.goto(`${base}/ask`);
  await settle(phone, 1200);
  await shot(phone, 'phone-3-ask');
  await phone.goto(`${base}/settings?tab=connections`);
  await phone
    .getByRole('region', { name: 'Live payments' })
    .getByRole('button', { name: 'Send next live payment' })
    .click();
  await phone.getByRole('listitem').filter({ hasText: 'Simulated payment' }).first().waitFor();
  await settle(phone, 900);
  await shot(phone, 'phone-4-payment-card');
  await pctx.close();

  await browser.close();
  console.log(`Screenshots written to ${out}`);
} finally {
  stop();
}
