import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useState } from 'react';

import { motion as tokens } from '../tokens/tokens';

/**
 * Shows an already-formatted value. When the value changes after first render (because the
 * API returned a new number after a user action), the old text slides out and the new one in.
 * The first render never animates; reduced motion swaps instantly.
 */
export function NumberTicker({ value, className }: { value: string; className?: string }) {
  const reduce = useReducedMotion();
  const [seen, setSeen] = useState({ value, direction: 1 as 1 | -1, changed: false });

  // Track direction when the value changes (adjusting state during render).
  if (seen.value !== value) {
    const direction = value.localeCompare(seen.value, 'en-IN', { numeric: true }) >= 0 ? 1 : -1;
    setSeen({ value, direction, changed: true });
  }

  if (reduce) return <span className={className}>{value}</span>;

  return (
    <span className={`relative inline-flex overflow-hidden ${className ?? ''}`}>
      <AnimatePresence initial={false} mode="popLayout">
        <motion.span
          key={value}
          initial={seen.changed ? { y: `${seen.direction * 60}%`, opacity: 0 } : false}
          animate={{ y: '0%', opacity: 1 }}
          exit={{ y: `${seen.direction * -60}%`, opacity: 0 }}
          transition={{ duration: tokens.ticker / 1000, ease: tokens.easeArray }}
        >
          {value}
        </motion.span>
      </AnimatePresence>
    </span>
  );
}
