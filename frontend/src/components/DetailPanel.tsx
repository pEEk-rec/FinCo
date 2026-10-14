import { X } from '@phosphor-icons/react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import type { ReactNode } from 'react';

import { copy } from '../copy/en';
import { motion as tokens } from '../tokens/tokens';

/** Right-hand detail pane that slides in when something is selected. */
export function DetailPanel({
  openKey,
  title,
  onClose,
  children,
  empty,
}: {
  openKey: string | null;
  title: string;
  onClose: () => void;
  children: ReactNode;
  empty: ReactNode;
}) {
  const reduce = useReducedMotion();
  return (
    <aside
      aria-label={title}
      className="flex h-full min-w-0 flex-col border-l border-hairline bg-surface"
    >
      <AnimatePresence mode="wait" initial={false}>
        {openKey ? (
          <motion.div
            key={openKey}
            initial={reduce ? { opacity: 0 } : { opacity: 0, x: 16 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: tokens.base / 1000, ease: tokens.easeArray }}
            className="flex min-h-0 flex-1 flex-col"
          >
            <div className="flex h-12 items-center justify-between border-b border-hairline px-6">
              <span className="label-mono text-ink-3">{title}</span>
              <button
                type="button"
                onClick={onClose}
                aria-label={copy.common.close}
                className="rounded-[6px] p-1.5 text-ink-3 hover:bg-surface-sunken hover:text-ink"
              >
                <X size={16} aria-hidden />
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
          </motion.div>
        ) : (
          <motion.div
            key="empty"
            className="flex flex-1 items-center justify-center p-8 text-center"
          >
            {empty}
          </motion.div>
        )}
      </AnimatePresence>
    </aside>
  );
}
