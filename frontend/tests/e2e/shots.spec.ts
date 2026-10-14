import { expect, test } from '@playwright/test';

import { signIn } from './helpers';

const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '1024x768', width: 1024, height: 768 },
  { name: '390x844', width: 390, height: 844 },
];
const SCREENS = [
  { name: 'welcome', path: '/welcome' },
  { name: 'dashboard', path: '/' },
  { name: 'transactions', path: '/transactions?period=2024-03' },
  { name: 'review', path: '/review' },
  { name: 'monthly', path: '/monthly?period=2024-02' },
  { name: 'agent', path: '/agent' },
  { name: 'connect', path: '/connect' },
  { name: 'design', path: '/design' },
];

// Runs after the demo project, so the database already holds imported data.
for (const viewport of VIEWPORTS) {
  test(`screenshots at ${viewport.name}`, async ({ page }) => {
    await signIn(page);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const screen of SCREENS) {
      await page.goto(screen.path);
      await page.waitForLoadState('networkidle');
      await page.waitForTimeout(1200); // let chart draw-in finish
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
