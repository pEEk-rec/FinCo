// @vitest-environment node
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

const root = fileURLToPath(new URL('../..', import.meta.url));
const run = (script: string, ...args: string[]) =>
  spawnSync(process.execPath, [`scripts/${script}`, ...args], { cwd: root, encoding: 'utf8' });

describe('honesty and design gates', () => {
  it('app source contains no literal figures', () => {
    const result = run('check_no_literal_figures.mjs');
    expect(result.stderr).toBe('');
    expect(result.status).toBe(0);
  });

  it('the figure check can fail: a seeded violation is caught by every rule', () => {
    const result = run('check_no_literal_figures.mjs', 'tests/fixtures/figures-violation');
    expect(result.status).toBe(1);
    expect(result.stderr).toContain('digits in JSX text');
    expect(result.stderr).toContain('currency next to digits');
    expect(result.stderr).toContain('percentage in a string');
  });

  it('every token pair passes WCAG AA', () => {
    expect(run('check_contrast.mjs').status).toBe(0);
  });

  it('every font stack renders ₹ and has tabular figures', () => {
    expect(run('check_glyphs.mjs').status).toBe(0);
  });

  it('generated token CSS is up to date with tokens.ts', () => {
    expect(run('build_tokens.mjs', '--check').status).toBe(0);
  });
});
