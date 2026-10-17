/**
 * The single source of design tokens. `scripts/build_tokens.mjs` turns this file into
 * `src/tokens/generated.css` (CSS variables + Tailwind theme); `scripts/check_contrast.mjs`
 * checks every pair in `contrastPairs`. Components never use raw hex values.
 *
 * Colour semantics are strict: ink = action, positive = good, attention = needs a look,
 * negative = over or failed, agent (violet) = AI-derived or agent surfaces only.
 */

export const colors = {
  // Warm paper lit by coral: a serious ledger with a living accent. Coral is the brand and the
  // colour of money in motion; deep green, amber and crimson carry meaning; violet marks the AI.
  canvas: '#FBF6F2',
  surface: '#FFFFFF',
  'surface-sunken': '#F4ECE6',
  'surface-hover': '#FDF8F5',
  'surface-selected': '#FCEAE3',
  hairline: '#EADFD7',
  'hairline-strong': '#D9C8BD',
  'input-border': '#8C7B70',
  ink: '#1F1A17',
  'ink-2': '#4F4540',
  'ink-3': '#6B605A',
  'ink-inverse': '#FFFFFF',
  brand: '#BA3A25',
  'brand-ink': '#FFFFFF',
  'brand-tint': '#FDECE7',
  coral: '#FF7A5C',
  peach: '#FFB68C',
  gold: '#9A600A',
  'gold-tint': '#FBF0DA',
  positive: '#0F7A5A',
  'positive-tint': '#E2F3EC',
  attention: '#975300',
  'attention-tint': '#FCEFD9',
  negative: '#B3261E',
  'negative-tint': '#FCE6E3',
  agent: '#5B47D6',
  'agent-tint': '#ECE8FD',
  focus: '#2F5BD3',
} as const;

/** Muted category hues: `fg` text on `bg` tint for pills; `mark` for chart strokes/particles. */
export const categoryPalette = [
  { fg: '#8A3B1F', bg: '#F7E6DD', mark: '#C2603A' },
  { fg: '#4D581C', bg: '#ECEFD9', mark: '#7C8C35' },
  { fg: '#135C63', bg: '#DDEFF0', mark: '#2A8C96' },
  { fg: '#7A2E58', bg: '#F4E2EC', mark: '#B04E83' },
  { fg: '#2F4A78', bg: '#E1E8F4', mark: '#4F6FA8' },
  { fg: '#6A4A24', bg: '#F1E8DC', mark: '#9C7340' },
  { fg: '#3E5560', bg: '#E3EAED', mark: '#62808E' },
  { fg: '#8C2F45', bg: '#F6E1E6', mark: '#C04E68' },
  { fg: '#6E5208', bg: '#F5ECD3', mark: '#B08A2A' },
  { fg: '#1F5A7A', bg: '#DEEDF5', mark: '#3C88B0' },
  { fg: '#2D5A3A', bg: '#E2EEE5', mark: '#4E8A5E' },
  { fg: '#4D514D', bg: '#EFEDE7', mark: '#8A8E89' },
] as const;

export const radius = { control: '12px', card: '20px', chip: '999px' } as const;

export const shadow = { popover: '0 16px 40px rgba(80, 40, 20, 0.14)' } as const;

export const motion = {
  fast: 150,
  base: 240,
  slow: 600,
  chart: 900,
  ticker: 500,
  ease: 'cubic-bezier(0.2, 0.7, 0.2, 1)',
  easeArray: [0.2, 0.7, 0.2, 1] as const,
} as const;

export const fonts = {
  serif: "'Newsreader Variable', 'Geist Sans', Georgia, serif",
  sans: "'Geist Sans', system-ui, sans-serif",
  mono: "'Geist Mono', 'Geist Sans', ui-monospace, monospace",
} as const;

/** [size px, line-height, weight] — see PLAN_UI 2.3. */
export const typeScale = {
  display: [64, 1.0, 300],
  h1: [32, 1.15, 300],
  h2: [20, 1.3, 500],
  body: [15, 1.5, 400],
  small: [13, 1.45, 400],
  label: [11, 1.4, 500],
  hero: [48, 1.0, 300],
  cell: [14, 1.4, 400],
} as const;

type ColorName = keyof typeof colors;

/**
 * Every foreground/background pair used for text or UI components.
 * kind 'text' needs 4.5:1, 'large' (24px+ or 19px bold) and 'ui' need 3:1.
 */
export const contrastPairs: { fg: ColorName; bg: ColorName; kind: 'text' | 'large' | 'ui' }[] = [
  ...(
    ['canvas', 'surface', 'surface-sunken', 'surface-hover', 'surface-selected'] as const
  ).flatMap((bg) => [
    { fg: 'ink' as const, bg, kind: 'text' as const },
    { fg: 'ink-2' as const, bg, kind: 'text' as const },
    { fg: 'ink-3' as const, bg, kind: 'text' as const },
  ]),
  { fg: 'ink-inverse', bg: 'ink', kind: 'text' },
  { fg: 'brand-ink', bg: 'brand', kind: 'text' },
  { fg: 'brand', bg: 'surface', kind: 'text' },
  { fg: 'brand', bg: 'brand-tint', kind: 'text' },
  { fg: 'gold', bg: 'surface', kind: 'text' },
  { fg: 'gold', bg: 'gold-tint', kind: 'text' },
  { fg: 'brand', bg: 'canvas', kind: 'text' },
  { fg: 'positive', bg: 'surface', kind: 'text' },
  { fg: 'positive', bg: 'positive-tint', kind: 'text' },
  { fg: 'attention', bg: 'surface', kind: 'text' },
  { fg: 'attention', bg: 'attention-tint', kind: 'text' },
  { fg: 'negative', bg: 'surface', kind: 'text' },
  { fg: 'negative', bg: 'negative-tint', kind: 'text' },
  { fg: 'agent', bg: 'surface', kind: 'text' },
  { fg: 'agent', bg: 'agent-tint', kind: 'text' },
  { fg: 'agent', bg: 'canvas', kind: 'text' },
  { fg: 'input-border', bg: 'surface', kind: 'ui' },
  { fg: 'focus', bg: 'surface', kind: 'ui' },
  { fg: 'focus', bg: 'canvas', kind: 'ui' },
  { fg: 'positive', bg: 'surface-sunken', kind: 'ui' },
  { fg: 'attention', bg: 'surface-sunken', kind: 'ui' },
  { fg: 'negative', bg: 'surface-sunken', kind: 'ui' },
];
