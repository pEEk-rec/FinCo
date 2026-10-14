import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

import { getJson, signIn } from './helpers';

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

test('welcome page is restrained and links to the app', async ({ page }) => {
  await page.goto('/welcome');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('ledger');
  await expect(page.getByText('It cannot move money.')).toBeVisible();
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
