import { describe, expect, it } from 'vitest';

import { displayName } from '../../src/format/name';

describe('displayName', () => {
  it('turns a shouted bank name into a readable one', () => {
    expect(displayName('GUPTA JUICE CENTRE')).toBe('Gupta Juice Centre');
    expect(displayName('RAMESH K')).toBe('Ramesh K');
    expect(displayName("DOMINO'S PIZZA")).toBe("Domino's Pizza");
  });
  it('leaves a name that is already mixed case alone', () => {
    expect(displayName('Swiggy')).toBe('Swiggy');
    expect(displayName('McDonalds')).toBe('McDonalds');
    expect(displayName('chaistall@okaxis')).toBe('chaistall@okaxis');
  });
  it('does not touch a very short or empty name', () => {
    expect(displayName('')).toBe('');
    expect(displayName('K')).toBe('K');
  });
});
