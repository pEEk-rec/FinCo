// WCAG 2.x contrast check for every token pair in tokens.contrastPairs, plus category pills.
// Fails (exit 1) below AA: 4.5:1 normal text, 3:1 large text and UI components.
const { colors, categoryPalette, contrastPairs } = await import('../src/tokens/tokens.ts');

function luminance(hex) {
  const channels = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const MIN = { text: 4.5, large: 3, ui: 3 };
const rows = contrastPairs.map((p) => ({
  label: `${p.fg} on ${p.bg}`,
  ratio: contrast(colors[p.fg], colors[p.bg]),
  min: MIN[p.kind],
}));
categoryPalette.forEach((c, i) => {
  rows.push({ label: `cat-${i + 1} fg on bg`, ratio: contrast(c.fg, c.bg), min: MIN.text });
  rows.push({
    label: `cat-${i + 1} mark on surface`,
    ratio: contrast(c.mark, colors.surface),
    min: MIN.ui,
  });
});

let failed = 0;
for (const row of rows) {
  const ok = row.ratio >= row.min;
  if (!ok) failed++;
  if (!ok || process.argv.includes('--verbose')) {
    console.log(
      `${ok ? 'ok  ' : 'FAIL'} ${row.ratio.toFixed(2).padStart(5)} >= ${row.min}  ${row.label}`,
    );
  }
}
console.log(`contrast: ${rows.length - failed}/${rows.length} pairs pass AA`);
if (failed) process.exit(1);
