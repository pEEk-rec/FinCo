import { motion, useReducedMotion } from 'motion/react';
import { useId, useState, type MouseEvent, type ReactNode } from 'react';

import { motion as tokens } from '../tokens/tokens';

export type LiquidTone = 'brand' | 'positive' | 'attention' | 'negative' | 'agent' | 'gold';

const TONE: Record<LiquidTone, { top: string; bottom: string }> = {
  brand: { top: 'var(--color-coral)', bottom: 'var(--color-brand)' },
  positive: { top: 'var(--color-positive)', bottom: 'var(--color-positive)' },
  attention: { top: 'var(--color-peach)', bottom: 'var(--color-attention)' },
  negative: { top: 'var(--color-coral)', bottom: 'var(--color-negative)' },
  agent: { top: 'var(--color-agent)', bottom: 'var(--color-focus)' },
  gold: { top: 'var(--color-peach)', bottom: 'var(--color-gold)' },
};

/** A sine wave two periods wide so it can slide one period and loop without a seam. */
function wavePath(width: number, amp: number, phase: number): string {
  const period = width;
  const pts: string[] = [];
  for (let x = 0; x <= period * 2; x += 4) {
    const y = amp * Math.sin((x / period) * Math.PI * 2 + phase);
    pts.push(`${x === 0 ? 'M' : 'L'}${x} ${y.toFixed(2)}`);
  }
  return `${pts.join(' ')} L${period * 2} 400 L0 400 Z`;
}

/**
 * A glass vessel that fills with liquid in proportion to a value the API computed.
 * `fraction` runs from 0 to 1. The level glides to each new value. It is also a small toy:
 * hovering stirs the surface and tilts it towards the pointer, bubbles rise, and a click sends
 * a ripple out. Decoration only; the number it shows always comes from the API.
 */
export function LiquidVessel({
  fraction,
  tone = 'brand',
  size = 112,
  shape = 'circle',
  children,
}: {
  fraction: number;
  tone?: LiquidTone;
  size?: number;
  shape?: 'circle' | 'drop';
  children?: ReactNode;
}) {
  const reduce = useReducedMotion();
  const uid = useId().replace(/:/g, '');
  const [stirred, setStirred] = useState(false);
  const [tilt, setTilt] = useState(0);
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([]);
  const f = Math.min(1, Math.max(0, fraction));
  // Even an empty vessel shows a thin film so it never looks broken.
  const level = Math.max(f, 0.04);
  const y = 100 - level * 100;
  const c = TONE[tone];
  const outline =
    shape === 'circle'
      ? 'M50 4 A46 46 0 1 1 49.99 4 Z'
      : 'M50 4 C 50 4 88 44 88 66 A 38 38 0 0 1 12 66 C 12 44 50 4 50 4 Z';
  const spring = { type: 'spring' as const, stiffness: 120, damping: 12 };

  const local = (e: MouseEvent<HTMLDivElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    return {
      x: ((e.clientX - box.left) / box.width) * 100,
      y: ((e.clientY - box.top) / box.height) * 100,
    };
  };

  return (
    <div
      className="relative shrink-0 cursor-pointer select-none"
      style={{ width: size, height: size }}
      onPointerEnter={() => !reduce && setStirred(true)}
      onPointerLeave={() => {
        setStirred(false);
        setTilt(0);
      }}
      onPointerMove={(e) => {
        if (reduce) return;
        setTilt((local(e).x - 50) * 0.22);
      }}
      onClick={(e) => {
        if (reduce) return;
        const p = local(e);
        const id = Date.now();
        setRipples((r) => [...r.slice(-3), { id, ...p }]);
        window.setTimeout(() => setRipples((r) => r.filter((x) => x.id !== id)), 900);
      }}
    >
      <svg viewBox="0 0 100 100" className="h-full w-full overflow-visible" aria-hidden>
        <defs>
          <clipPath id={`clip-${uid}`}>
            <path d={outline} />
          </clipPath>
          <linearGradient id={`fill-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={c.top} stopOpacity="0.92" />
            <stop offset="1" stopColor={c.bottom} stopOpacity="0.95" />
          </linearGradient>
          <radialGradient id={`shine-${uid}`} cx="0.3" cy="0.2" r="0.8">
            <stop offset="0" stopColor="white" stopOpacity="0.55" />
            <stop offset="1" stopColor="white" stopOpacity="0" />
          </radialGradient>
        </defs>
        <g clipPath={`url(#clip-${uid})`}>
          <rect width="100" height="100" fill="var(--color-surface-sunken)" />
          <motion.g
            animate={{ rotate: tilt }}
            transition={spring}
            style={{ transformOrigin: '50px 50px', transformBox: 'view-box' }}
          >
            <motion.g
              initial={reduce ? false : { y: 100 }}
              animate={{ y }}
              transition={{ duration: tokens.chart / 1000, ease: tokens.easeArray }}
            >
              <g className="liquid-wave-back" style={{ opacity: 0.4 }}>
                <path d={wavePath(100, stirred ? 6 : 3, 1.4)} fill={`url(#fill-${uid})`} />
              </g>
              <g className={stirred ? 'liquid-wave-front liquid-fast' : 'liquid-wave-front'}>
                <path d={wavePath(100, stirred ? 5 : 2.4, 0)} fill={`url(#fill-${uid})`} />
              </g>
              {stirred
                ? [18, 46, 72].map((x, k) => (
                    <circle
                      key={x}
                      cx={x}
                      cy={70}
                      r={1.6 + k * 0.5}
                      fill="white"
                      opacity="0.7"
                      className="liquid-bubble"
                      style={{ animationDelay: `${k * 0.35}s` }}
                    />
                  ))
                : null}
            </motion.g>
          </motion.g>
          {ripples.map((r) => (
            <motion.circle
              key={r.id}
              cx={r.x}
              cy={r.y}
              fill="none"
              stroke="white"
              strokeWidth="1.5"
              initial={{ r: 2, opacity: 0.9 }}
              animate={{ r: 44, opacity: 0 }}
              transition={{ duration: 0.85, ease: 'easeOut' }}
            />
          ))}
          <rect width="100" height="100" fill={`url(#shine-${uid})`} />
        </g>
        <path d={outline} fill="none" stroke="var(--color-hairline-strong)" strokeWidth="1.5" />
      </svg>
      {children ? (
        <div className="tabular pointer-events-none absolute inset-0 flex items-center justify-center text-center [text-shadow:0_0_10px_var(--color-surface),0_0_2px_var(--color-surface)]">
          {children}
        </div>
      ) : null}
    </div>
  );
}

/**
 * A horizontal ribbon for one number against your own history.
 * The faint band is your usual range, the tick is your usual middle, the gold flag is the target,
 * and the liquid is where you are now. All positions come from API values.
 */
export function LiquidBand({
  value,
  target,
  usual,
  low,
  high,
  direction,
  label,
  tone = 'brand',
}: {
  value: number;
  target: number;
  usual: number | null;
  low: number | null;
  high: number | null;
  direction: 'lower' | 'higher';
  label: string;
  tone?: LiquidTone;
}) {
  const reduce = useReducedMotion();
  const uid = useId().replace(/:/g, '');
  const top = Math.max(value, target, high ?? 0, usual ?? 0, 1) * 1.12;
  const pct = (v: number) => `${Math.min(100, Math.max(0, (v / top) * 100))}%`;
  const c = TONE[tone];
  return (
    <div role="img" aria-label={label} className="w-full">
      <svg viewBox="0 0 400 64" className="h-16 w-full" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id={`band-${uid}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor={c.bottom} stopOpacity="0.8" />
            <stop offset="1" stopColor={c.top} stopOpacity="0.95" />
          </linearGradient>
        </defs>
        <rect x="0" y="22" width="400" height="20" rx="10" fill="var(--color-surface-sunken)" />
        {low !== null && high !== null ? (
          <rect
            x={(low / top) * 400}
            y="18"
            width={Math.max(4, ((high - low) / top) * 400)}
            height="28"
            rx="14"
            fill="var(--color-hairline-strong)"
            opacity="0.55"
          />
        ) : null}
        <motion.rect
          x="0"
          y="22"
          height="20"
          rx="10"
          fill={`url(#band-${uid})`}
          initial={reduce ? false : { width: 0 }}
          animate={{ width: Math.max(6, (value / top) * 400) }}
          transition={{ duration: tokens.chart / 1000, ease: tokens.easeArray }}
        />
        {usual !== null ? (
          <line
            x1={(usual / top) * 400}
            x2={(usual / top) * 400}
            y1="12"
            y2="52"
            stroke="var(--color-ink-3)"
            strokeWidth="1.5"
            strokeDasharray="2 3"
          />
        ) : null}
        <line
          x1={(target / top) * 400}
          x2={(target / top) * 400}
          y1="6"
          y2="58"
          stroke="var(--color-gold)"
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
      <div className="relative mt-1 h-4 text-small text-ink-3" aria-hidden>
        <span className="absolute -translate-x-1/2" style={{ left: pct(target) }}>
          <span className="text-gold">{direction === 'lower' ? 'cap' : 'goal'}</span>
        </span>
      </div>
    </div>
  );
}
