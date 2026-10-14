import { categoryPalette } from '../tokens/tokens';

/**
 * Category identity colour (display only): a stable index into the muted category palette,
 * derived from the category id so the same category always gets the same hue. The last
 * palette entry is reserved for "uncategorised".
 */
export function categoryHue(categoryId: string | null | undefined): number {
  const usable = categoryPalette.length - 1;
  if (!categoryId) return usable; // neutral
  let hash = 0;
  for (const ch of categoryId) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  return hash % usable;
}

export function categoryColors(categoryId: string | null | undefined) {
  const hue = categoryHue(categoryId);
  return { index: hue + 1, ...categoryPalette[hue]! };
}
