import { describe, expect, it } from 'vitest';

import { formatINR, groupIndian, MINUS, RUPEE, spokenINR } from '../../src/format/money';

describe('groupIndian', () => {
  it.each([
    ['0', '0'],
    ['999', '999'],
    ['1000', '1,000'],
    ['9999', '9,999'],
    ['10000', '10,000'],
    ['99999', '99,999'],
    ['100000', '1,00,000'],
    ['999999', '9,99,999'],
    ['1000000', '10,00,000'],
    ['9999999', '99,99,999'],
    ['10000000', '1,00,00,000'],
    ['123456789', '12,34,56,789'],
    ['1234567890', '1,23,45,67,890'],
  ])('%s -> %s', (input, expected) => {
    expect(groupIndian(input)).toBe(expected);
  });

  it('matches a brute-force reference at every grouping boundary', () => {
    const reference = (n: string) => {
      if (n.length <= 3) return n;
      const head = n.slice(0, -3);
      const parts: string[] = [];
      for (let i = head.length; i > 0; i -= 2) parts.unshift(head.slice(Math.max(0, i - 2), i));
      return `${parts.join(',')},${n.slice(-3)}`;
    };
    for (let digits = 1; digits <= 16; digits++) {
      for (const n of ['1'.padEnd(digits, '0'), '9'.repeat(digits), '1'.repeat(digits)]) {
        expect(groupIndian(n)).toBe(reference(n));
      }
    }
  });
});

describe('formatINR', () => {
  it.each([
    [0, `${RUPEE}0.00`],
    [1, `${RUPEE}0.01`],
    [99, `${RUPEE}0.99`],
    [100, `${RUPEE}1.00`],
    [49950, `${RUPEE}499.50`],
    [99999, `${RUPEE}999.99`],
    [100000, `${RUPEE}1,000.00`],
    [9999999, `${RUPEE}99,999.99`],
    [10000000, `${RUPEE}1,00,000.00`],
    [12345678990, `${RUPEE}12,34,56,789.90`],
    [-1, `${MINUS}${RUPEE}0.01`],
    [-123450, `${MINUS}${RUPEE}1,234.50`],
    [-10000000, `${MINUS}${RUPEE}1,00,000.00`],
  ])('%d paise -> %s', (paise, expected) => {
    expect(formatINR(paise)).toBe(expected);
  });

  it('formats the largest safe integer exactly', () => {
    expect(formatINR(Number.MAX_SAFE_INTEGER)).toBe(`${RUPEE}9,00,71,99,25,47,409.91`);
    expect(formatINR(-Number.MAX_SAFE_INTEGER)).toBe(`${MINUS}${RUPEE}9,00,71,99,25,47,409.91`);
  });

  it.each([0.5, 1.1, Number.NaN, Number.POSITIVE_INFINITY, Number.MAX_SAFE_INTEGER + 1])(
    'rejects %s',
    (bad) => {
      expect(() => formatINR(bad)).toThrow(TypeError);
    },
  );

  describe('paise display', () => {
    it.each([
      [100000, 'auto', `${RUPEE}1,000`],
      [100050, 'auto', `${RUPEE}1,000.50`],
      [100049, 'never', `${RUPEE}1,000`],
      [100050, 'never', `${RUPEE}1,001`], // half up
      [100051, 'never', `${RUPEE}1,001`],
      [-100050, 'never', `${MINUS}${RUPEE}1,001`], // half away from zero
      [-100049, 'never', `${MINUS}${RUPEE}1,000`],
      [49, 'never', `${RUPEE}0`],
      [50, 'never', `${RUPEE}1`],
      [-49, 'never', `${RUPEE}0`], // rounds to zero: no minus on zero
      [9999950, 'never', `${RUPEE}1,00,000`], // rounding crosses a grouping boundary
    ] as const)('%d with paise=%s -> %s', (paise, mode, expected) => {
      expect(formatINR(paise, { paise: mode })).toBe(expected);
    });
  });

  describe('sign display', () => {
    it('adds + only for positive values when asked', () => {
      expect(formatINR(500, { sign: 'always' })).toBe(`+${RUPEE}5.00`);
      expect(formatINR(0, { sign: 'always' })).toBe(`${RUPEE}0.00`);
      expect(formatINR(-500, { sign: 'always' })).toBe(`${MINUS}${RUPEE}5.00`);
    });
    it('drops the sign when asked', () => {
      expect(formatINR(-500, { sign: 'never' })).toBe(`${RUPEE}5.00`);
    });
    it('never uses a hyphen-minus', () => {
      expect(formatINR(-500)).not.toContain('-');
    });
  });

  it('can omit the symbol', () => {
    expect(formatINR(123456, { symbol: false })).toBe('1,234.56');
  });

  describe('compact (chart axes)', () => {
    it.each([
      [0, `${RUPEE}0`],
      [99949, `${RUPEE}999`],
      [99950, `${RUPEE}1,000`], // rounds up into the next step's raw form
      [100000, `${RUPEE}1K`],
      [149999, `${RUPEE}1.5K`],
      [144999, `${RUPEE}1.4K`],
      [9_999_900, `${RUPEE}100K`],
      [10_000_000, `${RUPEE}1L`],
      [12_500_000, `${RUPEE}1.3L`], // 1.25 -> 1.3 half up
      [999_999_900, `${RUPEE}100L`],
      [1_000_000_000, `${RUPEE}1Cr`],
      [123_456_789_000, `${RUPEE}123.5Cr`],
      [-12_500_000, `${MINUS}${RUPEE}1.3L`],
    ])('%d -> %s', (paise, expected) => {
      expect(formatINR(paise, { compact: true })).toBe(expected);
    });
  });
});

describe('spokenINR', () => {
  it('reads amounts for screen readers', () => {
    expect(spokenINR(123450)).toBe('1,234 rupees 50 paise');
    expect(spokenINR(-100)).toBe('minus 1 rupees');
    expect(spokenINR(0)).toBe('0 rupees');
  });
});

import { parseRupeesToPaise } from '../../src/format/money';

describe('parseRupeesToPaise', () => {
  it.each([
    ['2000', 200000],
    ['2,000', 200000],
    ['₹ 2,00,000.5', 20000050],
    ['0.01', 1],
    ['499.50', 49950],
  ])('%s -> %d', (text, expected) => {
    expect(parseRupeesToPaise(text)).toBe(expected);
  });
  it.each(['', 'abc', '0', '0.00', '-5', '1.234', '1e3', '12.', '.5', '9'.repeat(14)])(
    'rejects %j',
    (text) => {
      expect(parseRupeesToPaise(text)).toBeNull();
    },
  );
});
