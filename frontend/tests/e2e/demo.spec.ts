import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import { API, authHeaders, getJson, signIn } from './helpers';

test.describe.configure({ mode: 'serial' });

interface Queue {
  total: number;
}
interface Detail {
  transaction: { id: string; category_id: string | null };
  history: { undoable: boolean; event_type: string }[];
}

async function expectNoSeriousA11yIssues(page: Page, label: string): Promise<void> {
  await page.waitForTimeout(700); // let entrance animations finish: axe samples colours mid-fade
  const results = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  const serious = results.violations.filter(
    (v) => v.impact === 'serious' || v.impact === 'critical',
  );
  expect(
    serious.map((v) => `${label}: ${v.id} (${v.nodes.length}) ${v.nodes[0]?.html.slice(0, 120)}`),
  ).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await signIn(page);
});

test('welcome page is only the name, the promise, one button and three points', async ({
  page,
}) => {
  await page.goto('/welcome');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Every rupee, understood.');
  await expect(page.getByText('A calm ledger for living expenses.')).toBeVisible();
  await expect(page.getByRole('link', { name: 'FinCo' })).toBeVisible();
  await expect(page.getByRole('listitem')).toHaveCount(3);
  await expect(page.getByRole('link')).toHaveCount(2); // the name and the one button
  await expectNoSeriousA11yIssues(page, 'welcome');
  await page.getByRole('link', { name: 'Open the dashboard' }).click();
  await expect(page).toHaveURL(/:\d+\/$/);
});

test('empty dashboard says what to do, with no invented numbers', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByText('No transactions yet. Connect a bank to import your statements.'),
  ).toBeVisible();
  await expect(page.getByText('Demo data (synthetic)').first()).toBeVisible();
  const main = await page.locator('main').innerText();
  expect(main).not.toMatch(/\d/); // empty API: no digits on the page
});

test('connect, approve and import: the constellation shows real counts', async ({
  page,
  request,
}) => {
  await page.goto('/');
  await page.getByRole('link', { name: 'Connect a bank' }).click();
  await expect(page.getByText('Share bank data with FinCo')).toBeVisible();
  await expect(page.getByText('Pending', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Approve and import' }).click();
  await expect(page.getByText(/Fetched \d+ transactions/).first()).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByText(/Categorised by rule: \d+\. By AI: \d+\. Needs you: \d+\./).first(),
  ).toBeVisible();

  await page.waitForTimeout(2500); // let the particles settle
  await page.screenshot({ path: '.shots/connect/import-1440x900.png' });
  const queue = await getJson<Queue>(request, '/review-queue');
  expect(queue.total).toBeGreaterThan(0);
  await expectNoSeriousA11yIssues(page, 'connect');
});

test('dashboard shows the real month', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Left to spend')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('pace');
  await expect(page.getByRole('img', { name: /Spent, Ideal pace, Budget/ })).toBeVisible();
  await expect(page.getByText('Needs your review')).toBeVisible();
  await expectNoSeriousA11yIssues(page, 'dashboard');
});

test('review queue: pick with the keyboard, confirm, and the queue shrinks', async ({
  page,
  request,
}) => {
  const before = (await getJson<Queue>(request, '/review-queue')).total;
  await page.goto('/review');
  await expect(page.getByText('Why this needs you')).toBeVisible();
  await page.keyboard.press('1');
  await page.keyboard.press('Enter');
  await expect(page.getByText(/^Moved to /)).toBeVisible();
  await expect
    .poll(async () => (await getJson<Queue>(request, '/review-queue')).total)
    .toBe(before - 1);
  await expectNoSeriousA11yIssues(page, 'review');
});

test('transactions: correct a category, see it audited, undo it', async ({ page, request }) => {
  await page.goto('/transactions?period=2024-03');
  const rows = page.getByTestId('tx-row');
  await expect(rows.first()).toBeVisible();
  await rows.first().click();
  const detailAside = page.getByRole('complementary', { name: 'Transactions' });
  await expect(detailAside.getByText('History')).toBeVisible();
  const id = new URL(page.url()).searchParams.get('tx') as string;
  const before = await getJson<Detail>(request, `/transactions/${id}`);

  await detailAside.getByTestId('category-trigger').click();
  await page.getByRole('listbox').getByRole('option', { name: 'Education', exact: true }).click();
  await expect(page.getByText('Moved to Education.')).toBeVisible();
  await expect(detailAside.getByText(/Category changed from/)).toBeVisible();
  const changed = await getJson<Detail>(request, `/transactions/${id}`);
  expect(changed.transaction.category_id).toBe('education');
  expect(changed.history.some((h) => h.undoable)).toBe(true);

  await page.getByRole('status').getByRole('button', { name: 'Undo' }).click();
  await expect
    .poll(
      async () => (await getJson<Detail>(request, `/transactions/${id}`)).transaction.category_id,
    )
    .toBe(before.transaction.category_id);
  await expectNoSeriousA11yIssues(page, 'transactions');
});

test('monthly review: generate, explain, approve', async ({ page }) => {
  await page.goto('/monthly?period=2024-02');
  await page.getByRole('button', { name: 'Generate review' }).click();
  await expect(page.getByText('Findings', { exact: true })).toBeVisible();
  await expect(page.getByText('Suggestions', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Explain' }).first().click();
  await expect(page.getByText('Evidence').first()).toBeVisible();
  await page.getByRole('button', { name: 'Approve', exact: true }).first().click();
  await expect(page.getByText('Approved', { exact: true }).first()).toBeVisible();
  await expectNoSeriousA11yIssues(page, 'monthly');
});

test('agent process: understand, plan, act, with the investigation and what-if inline', async ({
  page,
}) => {
  await page.goto('/agent');
  await page.getByRole('button', { name: 'Why did my food spend change in February?' }).click();
  await expect(page.getByTestId('ask-answer')).toBeVisible();
  await expect(page.getByTestId('ask-process')).not.toHaveAttribute('open', '');
  await page.getByText('Show how the agent worked').click();
  await expect(page.getByText('How the agent worked', { exact: true })).toBeVisible();
  await expect(page.getByText('2 steps, proposed by deterministic planner')).toBeVisible();
  await expect(page.getByText('Ran 2 tools through the executor')).toBeVisible();
  await expect(page.getByText('Hypotheses tested')).toBeVisible();
  await page.screenshot({ path: '.shots/agent/ask-explain-1440x900.png', fullPage: true });

  await page
    .getByRole('textbox', { name: 'Ask', exact: true })
    .fill('what if I spend ₹2,000 more on food each month for 3 months');
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
  await expect(page.getByTestId('ask-answer')).toBeVisible();
  await page.getByText('Show how the agent worked').click();
  await expect(
    page.getByText('Compare the scenario with your current trajectory, month by month'),
  ).toBeVisible();
  await expect(page.getByText('Drafted a recommendation and waits for you')).toBeVisible();
  await page.screenshot({ path: '.shots/agent/ask-whatif-1440x900.png', fullPage: true });

  await page.getByRole('button', { name: 'Should I invest in mutual funds?' }).click();
  await expect(page.getByText('The agent cannot do that.')).toBeVisible();
  await expect(page.getByText('Stopped at the gate')).toBeVisible();
  await page.screenshot({ path: '.shots/agent/ask-refusal-1440x900.png', fullPage: true });
});

test('agent: refusal is plain, investigation shows evidence, what-if compares', async ({
  page,
}) => {
  await page.goto('/agent');
  await page.getByRole('textbox', { name: 'Ask', exact: true }).fill('transfer 5000 to rahul');
  await page.getByRole('button', { name: 'Ask', exact: true }).click();
  await expect(page.getByText('The agent cannot do that.')).toBeVisible();

  await page.getByRole('tab', { name: 'Investigate' }).click();
  await page.getByRole('button', { name: 'Investigate' }).first().click();
  await expect(page.getByText('Hypotheses tested')).toBeVisible();

  await page.getByRole('tab', { name: 'What if' }).click();
  await page.getByRole('button', { name: 'Compare with now' }).click();
  await expect(page.getByText('Monthly surplus: now and with this change')).toBeVisible();

  await page.getByRole('tab', { name: 'Goals and alerts' }).click();
  await expect(page.getByText('Laptop fund')).toBeVisible();

  await page.getByRole('tab', { name: 'Activity' }).click();
  await expect(page.getByText('Activity').first()).toBeVisible();
  await page.screenshot({ path: '.shots/agent/activity-1440x900.png' });
  await expectNoSeriousA11yIssues(page, 'agent');
});

test('backend down is a designed state, not a blank page', async ({ page }) => {
  await page.route('**/api/session', (route) => route.abort());
  await page.goto('/');
  await expect(page.getByText('This could not be loaded')).toBeVisible();
  await expect(page.getByText(/not running/)).toBeVisible();
});

test('the URL token logs in and is removed from the address bar', async ({ browser }) => {
  const context = await browser.newContext(); // no stored token
  const page = await context.newPage();
  await page.goto('/welcome#token=e2e-token');
  await page.getByRole('link', { name: 'Open the dashboard' }).click();
  await expect(page.getByText('Left to spend')).toBeVisible();
  expect(page.url()).not.toContain('token');
  await context.close();
});

test('goals: create, add money, edit, pause, finish; every figure comes from the API', async ({
  page,
  request,
}) => {
  await page.goto('/goals');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('saving for');
  await page.getByRole('button', { name: 'New goal' }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('What are you saving for').fill('Camera lens');
  await dialog.getByLabel('Target (rupees)').fill('50000');
  await dialog.getByLabel('By when (optional)').fill('2030-01-31');
  await dialog.getByRole('button', { name: 'Create goal' }).click();
  await expect(page.getByRole('heading', { name: 'Camera lens', exact: true })).toBeVisible();
  const card = page.locator('li', {
    has: page.getByRole('heading', { name: 'Camera lens', exact: true }),
  });
  await expectNoSeriousA11yIssues(page, 'goals');

  await card.getByRole('button', { name: 'Add money' }).click();
  await page.getByLabel('Amount to add to Camera lens').fill('12500');
  await card.getByRole('button', { name: 'Add', exact: true }).click();
  await expect(card.getByText('₹12,500', { exact: false })).toBeVisible();

  const goals = await getJson<{
    goals: { id: string; name: string; current_paise: number; status: string }[];
    progress: { goal_id: string; percent_bp: number; current_paise: number }[];
  }>(request, '/goals');
  const lens = goals.goals.find((g) => g.name === 'Camera lens');
  expect(goals.progress.find((p) => p.goal_id === lens?.id)?.current_paise).toBe(1250000);
  expect(goals.progress.find((p) => p.goal_id === lens?.id)?.percent_bp).toBe(2500);
  await expect(card.getByText('25%')).toBeVisible();

  await card.getByRole('button', { name: 'Pause' }).click();
  await expect(card.getByText('Paused')).toBeVisible();
  await card.getByRole('button', { name: 'Resume' }).click();
  await card.getByRole('button', { name: 'Mark finished' }).click();
  await expect(page.getByRole('heading', { name: 'Finished' })).toBeVisible();
});

test('challenges: find one, start it, pause, resume; progress shows the level', async ({
  page,
  request,
}) => {
  await page.goto('/challenges');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('honestly measured');
  await page.getByRole('button', { name: 'Look for a challenge' }).click();
  const start = page.getByRole('button', { name: 'Start this challenge' });
  await expect(start.first()).toBeVisible();
  await expectNoSeriousA11yIssues(page, 'challenges');

  await start.first().click();
  await expect(page.getByRole('heading', { name: 'In progress' })).toBeVisible();
  const coach = await getJson<{ active: { id: string; status: string; title: string }[] }>(
    request,
    '/coach',
  );
  expect(coach.active).toHaveLength(1);
  const title = coach.active[0]!.title;
  const card = page.locator('li', { has: page.getByRole('heading', { name: title, exact: true }) });

  await card.getByRole('button', { name: 'Pause' }).click();
  await expect(card.getByText('Paused', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Resume' }).click();
  await expect(card.getByRole('button', { name: 'Pause' })).toBeVisible();

  await page.goto('/progress');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('kept honest');
  await expect(page.getByText('Level', { exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Badges' })).toBeVisible();
  await expectNoSeriousA11yIssues(page, 'progress');
});

test('capture: simulate a payment, tag it with a key, undo, then tag through Other', async ({
  page,
  request,
}) => {
  await page.goto('/capture');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('as they happen');
  await expect(page.getByText('All caught up')).toBeVisible();

  const simulate = async (utr: string, who: string) => {
    await page.getByLabel('Amount (rupees)').fill('250');
    await page.getByLabel('To', { exact: true }).fill(who);
    await page.getByRole('button', { name: 'Send the alert' }).click();
    await expect(page.getByRole('article', { name: new RegExp(who, 'i') })).toBeVisible();
    return utr;
  };

  await simulate('a', 'Corner Juice Shop');
  const card = page.getByRole('article', { name: /Corner Juice Shop/i });
  await expect(card.getByText('Simulated payment')).toBeVisible();
  await expect(page.getByText('What the phone would have sent')).toBeVisible();
  await expectNoSeriousA11yIssues(page, 'capture');

  // tag with the keyboard: the first guess
  await page.keyboard.press('1');
  await expect(page.getByText(/^Tagged /)).toBeVisible();
  await expect(card).toHaveCount(0);
  let inbox = await getJson<{ pending_count: number }>(request, '/capture/inbox');
  expect(inbox.pending_count).toBe(0);

  // undo brings it back
  await page.getByRole('button', { name: 'Undo' }).click();
  await expect(page.getByRole('article', { name: /Corner Juice Shop/i })).toBeVisible();

  // tag through the quick sheet with a search
  await page.getByRole('button', { name: 'Other…' }).click();
  const sheet = page.getByRole('dialog');
  await sheet.getByLabel('Search categories').fill('shop');
  await sheet.getByRole('list', { name: 'Categories' }).getByRole('button').first().click();
  await expect(page.getByRole('article', { name: /Corner Juice Shop/i })).toHaveCount(0);
  inbox = await getJson<{ pending_count: number }>(request, '/capture/inbox');
  expect(inbox.pending_count).toBe(0);
});

test('capture overlay: a payment interrupts on any page, Later sends it to the inbox', async ({
  page,
  request,
}) => {
  const simulate = async (who: string, vpa?: string) => {
    const res = await request.post(`${API}/capture/simulate`, {
      headers: authHeaders,
      data: { bank: 'axis', kind: 'debit', amount_paise: 31000, counterparty: who, vpa },
    });
    expect(res.ok()).toBeTruthy();
    return (await res.json()) as { event: { id: string } };
  };

  await page.goto('/goals');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('saving for');
  await simulate('Lakeside Tea Traders');
  const overlay = page.getByRole('article', { name: /Lakeside Tea Traders/i });
  await expect(overlay).toBeVisible({ timeout: 10_000 });
  await expect(overlay.getByText('Simulated payment')).toBeVisible();
  await expectNoSeriousA11yIssues(page, 'overlay');

  // Escape means later: it leaves the screen but stays in the inbox
  await page.keyboard.press('Escape');
  await expect(overlay).toHaveCount(0);
  const inbox = await getJson<{ pending_count: number }>(request, '/capture/inbox');
  expect(inbox.pending_count).toBe(1);

  // a second payment prompts again; a key tags it from this page
  await simulate('Harbour Fruit Traders');
  const second = page.getByRole('article', { name: /Harbour Fruit Traders/i });
  await expect(second).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('1');
  await expect(second).toHaveCount(0);
  await expect(page.getByText(/^Tagged /).first()).toBeVisible();

  // the one sent to later is waiting on the Tag payments page, and the overlay stays out of the way
  await page.goto('/capture');
  await expect(page.getByRole('article', { name: /Lakeside Tea Traders/i })).toBeVisible();
  await page
    .getByRole('article', { name: /Lakeside Tea Traders/i })
    .getByRole('button')
    .first()
    .click();
  await expect(page.getByText('All caught up')).toBeVisible();
});

test('today: money in and out, tag what is left, change what was tagged for you', async ({
  page,
  request,
}) => {
  const simulate = async (data: Record<string, unknown>) => {
    const res = await request.post(`${API}/capture/simulate`, { headers: authHeaders, data });
    expect(res.ok()).toBeTruthy();
    return (await res.json()) as { event: { id: string } };
  };
  await simulate({
    bank: 'axis',
    kind: 'debit',
    amount_paise: 41000,
    counterparty: 'Morning Bakery Traders',
  });
  await simulate({
    bank: 'axis',
    kind: 'credit',
    amount_paise: 250000,
    counterparty: 'Priya S',
    vpa: 'priya.s@okaxis',
  });

  await page.goto('/today');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('what is left to tag');
  await expect(page.getByRole('heading', { name: 'Needs you' })).toBeVisible();
  await expect(page.getByText('Money in')).toBeVisible();
  await expect(page.getByText('Money out')).toBeVisible();
  await expect(page.getByRole('article', { name: /Morning Bakery Traders/i })).toBeVisible();
  await expect(page.getByRole('article', { name: /Priya S/i })).toBeVisible();
  await expectNoSeriousA11yIssues(page, 'today');

  // tag the payment out with its first guess, and the credit through Other
  await page
    .getByRole('article', { name: /Morning Bakery Traders/i })
    .getByRole('button')
    .first()
    .click();
  await expect(page.getByRole('heading', { name: 'Tagged by you' })).toBeVisible();
  const credit = page.getByRole('article', { name: /Priya S/i });
  await credit.getByRole('button', { name: 'Other…' }).click();
  await page
    .getByRole('dialog')
    .getByRole('list', { name: 'Categories' })
    .getByRole('button')
    .first()
    .click();
  await expect(page.getByRole('article', { name: /Priya S/i })).toHaveCount(0);

  const today = await getJson<{
    totals: { in_paise: number; out_paise: number };
    counts: { needs_you: number; by_you: number };
  }>(request, '/capture/today');
  expect(today.totals.in_paise).toBeGreaterThanOrEqual(250000);
  expect(today.totals.out_paise).toBeGreaterThanOrEqual(41000);
  expect(today.counts.needs_you).toBe(0);

  // a tagged row can be changed
  await page.getByRole('button', { name: 'Change' }).first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
});

test('a tapped notification link opens that payment, and the app is installable', async ({
  page,
  request,
}) => {
  const res = await request.post(`${API}/capture/simulate`, {
    headers: authHeaders,
    data: {
      bank: 'axis',
      kind: 'debit',
      amount_paise: 55500,
      counterparty: 'Lantern Cafe Traders',
    },
  });
  expect(res.ok()).toBeTruthy();
  const inbox = await getJson<{ prompts: { prompt_id: string }[] }>(request, '/capture/inbox');
  const id = inbox.prompts[0]!.prompt_id;
  await page.goto(`/capture?prompt=${id}`);
  await expect(page.getByRole('dialog').getByText('What was this?')).toBeVisible();
  await page.keyboard.press('Escape');

  const manifest = await page.request.get('/manifest.webmanifest');
  expect(manifest.ok()).toBeTruthy();
  const body = (await manifest.json()) as {
    name: string;
    display: string;
    icons: { sizes: string }[];
  };
  expect(body.name).toBe('FinCo');
  expect(body.display).toBe('standalone');
  expect(body.icons.map((i) => i.sizes)).toEqual(expect.arrayContaining(['192x192', '512x512']));
  const sw = await page.request.get('/sw.js');
  expect(sw.ok()).toBeTruthy();
  expect(await sw.text()).toContain('notificationclick');
  expect((await page.request.get('/icons/icon-192.png')).ok()).toBeTruthy();

  await page.goto('/');
  await expect(page.getByRole('link', { name: /Review today/ })).toBeVisible();
});

test('bank link: set up, approve, fetch, then revoke stops it', async ({ page }) => {
  await page.goto('/connect');
  const card = page.getByRole('region', { name: 'Bank link' });
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: 'Set up the link' }).click();
  await expect(card.getByText('Waiting for approval')).toBeVisible();
  await expect(card.getByText('Customer', { exact: false })).toHaveCount(0); // plain words, not codes
  await expect(card.getByText('Fetched copies are deleted after', { exact: false })).toBeVisible();
  await card.getByRole('button', { name: 'Approve' }).click();
  await expect(card.getByText('Active', { exact: true })).toBeVisible();
  await card.getByRole('button', { name: 'Fetch now' }).click();
  await expect(card.getByRole('status')).toContainText('Added');
  await card.getByRole('button', { name: 'Revoke' }).click();
  await expect(card.getByText('Revoked', { exact: true })).toBeVisible();
  await expect(card.getByRole('button', { name: 'Fetch now' })).toHaveCount(0);
  await expectNoSeriousA11yIssues(page, 'bank link');
});
