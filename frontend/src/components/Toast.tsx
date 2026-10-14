import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import { copy } from '../copy/en';
import { motion as tokens } from '../tokens/tokens';

export interface ToastInput {
  message: string;
  tone?: 'neutral' | 'negative';
  /** Undo runs through the API; the toast shows its result. */
  onUndo?: () => Promise<void>;
}

interface ToastItem extends ToastInput {
  id: number;
}

const ToastContext = createContext<((toast: ToastInput) => void) | null>(null);

const VISIBLE_MS = 7000;

/** Bottom-left toast stack. One toast per action; Undo is always within reach. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);
  const reduce = useReducedMotion();

  const dismiss = useCallback((id: number) => {
    setItems((all) => all.filter((t) => t.id !== id));
  }, []);

  const show = useCallback(
    (toast: ToastInput) => {
      const id = nextId.current++;
      setItems((all) => [...all.slice(-2), { ...toast, id }]);
      window.setTimeout(() => dismiss(id), VISIBLE_MS);
    },
    [dismiss],
  );

  const value = useMemo(() => show, [show]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        className="no-print pointer-events-none fixed bottom-6 left-6 z-50 flex w-[min(26rem,calc(100vw-3rem))] flex-col gap-2"
      >
        <AnimatePresence initial={false}>
          {items.map((toast) => (
            <motion.div
              key={toast.id}
              layout={!reduce}
              initial={reduce ? { opacity: 0 } : { opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0 }}
              transition={{ duration: tokens.base / 1000, ease: tokens.easeArray }}
              className="pointer-events-auto flex items-center justify-between gap-4 rounded-control bg-ink px-4 py-3 text-small text-ink-inverse shadow-popover"
              role="status"
            >
              <span>{toast.message}</span>
              <span className="flex items-center gap-1">
                {toast.onUndo ? (
                  <button
                    type="button"
                    className="rounded-[6px] px-2 py-1 font-medium underline-offset-2 hover:underline"
                    onClick={async () => {
                      dismiss(toast.id);
                      await toast.onUndo?.();
                    }}
                  >
                    {copy.common.undo}
                  </button>
                ) : null}
                <button
                  type="button"
                  aria-label={copy.common.close}
                  className="rounded-[6px] px-2 py-1 opacity-70 hover:opacity-100"
                  onClick={() => dismiss(toast.id)}
                >
                  ×
                </button>
              </span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): (toast: ToastInput) => void {
  const show = useContext(ToastContext);
  if (!show) throw new Error('useToast must be used inside ToastProvider');
  return show;
}
