import { chromium } from '../../frontend/node_modules/playwright/index.mjs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1130 } });
await page.goto(pathToFileURL(join(here, 'diagram.html')).href);
await page.screenshot({ path: join(here, 'finco_architecture_flow.png'), fullPage: true });
await page.pdf({
  path: join(here, 'finco_architecture_flow.pdf'),
  width: '1600px',
  height: '1130px',
  printBackground: true,
});
for (const [i, id] of ['s1', 's2', 's3'].entries()) {
  await page
    .locator(`#${id}`)
    .locator('xpath=..')
    .screenshot({ path: join(here, `finco_flow_${i + 1}.png`) });
}
await browser.close();
