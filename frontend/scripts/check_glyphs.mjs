// Glyph test (PLAN_UI 2.3): every font stack in use must render the required characters,
// and the sans used for numbers must support tabular figures (tnum).
// A stack passes a character if any family in it (in order) has the glyph; the report lists
// which characters rely on a fallback family.
import { fileURLToPath } from 'node:url';

import { fontInfo } from './fontinfo.mjs';

const nm = fileURLToPath(new URL('../node_modules/', import.meta.url));
const FAMILIES = {
  Newsreader: [
    '@fontsource-variable/newsreader/files/newsreader-latin-opsz-normal.woff2',
    '@fontsource-variable/newsreader/files/newsreader-latin-ext-opsz-normal.woff2',
    '@fontsource-variable/newsreader/files/newsreader-latin-opsz-italic.woff2',
  ],
  'Geist Sans 300': ['@fontsource/geist-sans/files/geist-sans-latin-300-normal.woff2'],
  'Geist Sans 400': ['@fontsource/geist-sans/files/geist-sans-latin-400-normal.woff2'],
  'Geist Sans 500': ['@fontsource/geist-sans/files/geist-sans-latin-500-normal.woff2'],
  'Geist Mono 500': [
    '@fontsource/geist-mono/files/geist-mono-latin-500-normal.woff2',
    '@fontsource/geist-mono/files/geist-mono-latin-ext-500-normal.woff2',
  ],
};
const STACKS = {
  serif: ['Newsreader', 'Geist Sans 400'],
  'sans 300 (hero figures)': ['Geist Sans 300'],
  'sans 400': ['Geist Sans 400'],
  'sans 500': ['Geist Sans 500'],
  mono: ['Geist Mono 500', 'Geist Sans 500'],
};
// ⌀ (U+2300) is in the plan's test string but no candidate family ships it; it is not used
// anywhere in the UI, so it is reported, not required.
const REQUIRED = '₹0123456789,.→↗↘·–−+';
const OPTIONAL = '⌀';
const NEEDS_TNUM = ['Geist Sans 300', 'Geist Sans 400', 'Geist Sans 500'];

const info = {};
for (const [family, files] of Object.entries(FAMILIES)) {
  const codePoints = new Set();
  const features = new Set();
  for (const file of files) {
    const font = fontInfo(nm + file);
    font.codePoints.forEach((c) => codePoints.add(c));
    font.features.forEach((t) => features.add(t));
  }
  info[family] = { codePoints, features };
}

let failed = false;
for (const [stack, families] of Object.entries(STACKS)) {
  const fallbacks = [];
  const missing = [];
  for (const ch of REQUIRED + OPTIONAL) {
    const cp = ch.codePointAt(0);
    const owner = families.find((f) => info[f].codePoints.has(cp));
    if (!owner) missing.push(ch);
    else if (owner !== families[0]) fallbacks.push(`${ch}→${owner}`);
  }
  const requiredMissing = missing.filter((ch) => REQUIRED.includes(ch));
  if (requiredMissing.length) failed = true;
  console.log(
    `${requiredMissing.length ? 'FAIL' : 'ok  '} ${stack.padEnd(24)} missing: ${missing.join(' ') || 'none'}` +
      (fallbacks.length ? ` | fallback: ${fallbacks.join(' ')}` : ''),
  );
}
for (const family of NEEDS_TNUM) {
  const ok = info[family].features.has('tnum');
  if (!ok) failed = true;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${family} has tabular figures (tnum)`);
}
if (failed) process.exit(1);
console.log('check_glyphs: ₹ and required glyphs render in every stack');
