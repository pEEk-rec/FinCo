/**
 * The single source of design tokens. `scripts/build_tokens.mjs` turns this file into
 * `src/tokens/generated.css` (CSS variables + Tailwind theme); `scripts/check_contrast.mjs`
 * checks every pair in `contrastPairs`. Components never use raw hex values.
 *
 * Colour semantics are strict: ink = action, positive = good, attention = needs a look,
 * negative = over or failed, agent (violet) = AI-derived or agent surfaces only.
 */

export const colors = {
  canvas: '#F6F5F1',
  surface: '#FFFFFF',
  'surface-sunken': '#EFEDE7',
  'surface-hover': '#F9F8F5',
  'surface-selected': '#F1EFE9',
  hairline: '#E4E1D8',
  'hairline-strong': '#CFCBC0',
  'input-border': '#8E8A80',
  ink: '#121413',
  'ink-2': '#4D514D',
  'ink-3': '#686C67',
  'ink-inverse': '#FFFFFF',
  positive: '#0F6B53',
  'positive-tint': '#E3F1EC',
  attention: '#8F5605',
  'attention-tint': '#FBF1DC',
  negative: '#B4382A',
  'negative-tint': '#FBE8E4',
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

export const radius = { control: '8px', card: '14px', chip: '999px' } as const;

export const shadow = { popover: '0 8px 24px rgba(18, 20, 19, 0.08)' } as const;

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
