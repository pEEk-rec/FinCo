// Data honesty gate (PLAN_UI section 4): app code may not contain hardcoded figures.
// Scans frontend/src (tests and the /design entry live outside src and are not scanned).
//
// Fails on:
//   1. a currency marker next to digits      ("₹499", "Rs 20", "$5", "INR 100")
//   2. digits inside JSX text                 (<p>Spent 4,200 this month</p>)
//   3. a percentage inside a string literal   ("45% of budget")
//   4. digits inside any string in src/copy   (copy must take numbers as parameters)
//   5. digits in CSS `content:`
// A line can opt out with the comment `figures-ok: <reason>` (reviewed in code review).
//
// Usage: node scripts/check_no_literal_figures.mjs [dir]   (default: src)
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('..', import.meta.url));
const target = join(root, process.argv[2] ?? 'src');

const RULES = [
  { name: 'currency next to digits', re: /(₹|\bRs\.?|\bINR|\$)\s?\d|\d\s?₹/ },
  // A percent in prose ("45% of budget", "up 5%."), not a CSS length such as '-50%'.
  {
    name: 'percentage in a string',
    re: /["'`][^"'`\n]*\d\s?%(?:\s+[A-Za-z]|[.,;:!?])[^"'`\n]*["'`]/,
  },
];
const JSX_TEXT = /(?<![=<>-])>([^<>{}\n]*\d[^<>{}\n]*)</;
const CSS_CONTENT = /content\s*:\s*["'][^"']*\d/;
const STRING_WITH_DIGIT = /(["'`])(?:(?!\1)[^\\\n]|\\.)*\d(?:(?!\1)[^\\\n]|\\.)*\1/;

function* walk(dir) {
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* walk(path);
    else yield path;
  }
}

const SKIP = [`${sep}tokens${sep}`, `${sep}api${sep}schema.d.ts`];
const violations = [];
for (const file of walk(target)) {
  if (!/\.(tsx?|css)$/.test(file) || SKIP.some((s) => file.includes(s))) continue;
  const isCopy = file.includes(`${sep}copy${sep}`);
  // Blank out block comments, keeping newlines so line numbers stay right.
  const text = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, (m) =>
    m.replace(/[^\n]/g, ' '),
  );
  const lines = text.split('\n');
  lines.forEach((line, i) => {
    if (line.includes('figures-ok:')) return;
    const code = line.replace(/(^|\s)\/\/.*$/, '');
    const hits = RULES.filter((r) => r.re.test(code)).map((r) => r.name);
    if (file.endsWith('.tsx') && JSX_TEXT.test(code)) hits.push('digits in JSX text');
    if (file.endsWith('.css') && CSS_CONTENT.test(code)) hits.push('digits in CSS content');
    if (isCopy && STRING_WITH_DIGIT.test(code)) hits.push('digits in a copy string');
    for (const hit of hits) {
      violations.push(`${relative(root, file)}:${i + 1}: ${hit}: ${line.trim()}`);
    }
  });
}

if (violations.length) {
  console.error(violations.join('\n'));
  console.error(`check_no_literal_figures: ${violations.length} violation(s)`);
  process.exit(1);
}
console.log(`check_no_literal_figures: ${relative(root, target) || '.'} is clean`);
