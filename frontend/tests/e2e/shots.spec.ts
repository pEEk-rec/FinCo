import { expect, test } from '@playwright/test';

import { signIn } from './helpers';

const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1024x768', width: 1024, height: 768 },
  { name: '390x844', width: 390, height: 844 },
];
const SCREENS = [
  { name: 'welcome', path: '/welcome' },
  { name: 'overview', path: '/?period=2024-03' },
  { name: 'transactions', path: '/transactions?period=2024-03' },
  { name: 'transactions-by-category', path: '/transactions?period=2024-03&view=category' },
  { name: 'review', path: '/review' },
  { name: 'plan-review', path: '/plan?tab=review&period=2024-02' },
  { name: 'plan-budget', path: '/plan?tab=budget' },
  { name: 'plan-goals', path: '/plan?tab=goals' },
  { name: 'plan-bills', path: '/plan?tab=bills' },
  { name: 'plan-challenges', path: '/plan?tab=challenges' },
  { name: 'ask', path: '/ask' },
  { name: 'settings', path: '/settings' },
  { name: 'settings-connections', path: '/settings?tab=connections' },
  { name: 'design', path: '/design?demo=1' },
];

// Runs after the demo project, so the database already holds imported data.
for (const viewport of VIEWPORTS) {
  test(`screenshots at ${viewport.name}`, async ({ page }) => {
    await signIn(page);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const screen of SCREENS) {
      await page.goto(screen.path);
      await page.waitForLoadState('load');
      await page.waitForTimeout(2200); // data fetch and chart draw-in (the live stream never goes idle)
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${screen.name} scrolls sideways at ${viewport.name}`).toBeLessThanOrEqual(
        1,
      );
      await page.screenshot({
        path: `.shots/${screen.name}/populated-${viewport.name}.png`,
        fullPage: false,
      });
    }
  });
}
