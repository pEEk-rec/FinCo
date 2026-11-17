import {
  ArrowsLeftRight,
  CalendarBlank,
  GearSix,
  ListChecks,
  Sparkle,
  SquaresFour,
} from '@phosphor-icons/react';
import { motion, useReducedMotion } from 'motion/react';
import { createContext, useContext, useEffect, type ReactNode } from 'react';
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router';

import { ApiError } from '../api/client';
import { useCaptureInbox, useReviewQueue, useSession } from '../api/hooks';
import { copy } from '../copy/en';
import { LiquidBackdrop } from '../motion/LiquidBackdrop';
import { MonthProvider, MonthSwitcher } from '../state/month';
import { Badge } from './Badge';
import { CaptureOverlay } from './capture/CaptureOverlay';
import { cx } from './cx';
import { ErrorState } from './States';

interface NavDef {
  to: string;
  label: string;
  icon: (active: boolean) => ReactNode;
  end?: boolean;
}

const icon = (C: typeof SquaresFour) => (active: boolean) => (
  <C size={19} weight={active ? 'fill' : 'regular'} aria-hidden />
);

/** The whole product, in five places. Settings sits apart, below. */
const NAV: NavDef[] = [
  { to: '/', label: copy.nav.overview, icon: icon(SquaresFour), end: true },
  { to: '/transactions', label: copy.nav.transactions, icon: icon(ArrowsLeftRight) },
  { to: '/review', label: copy.nav.review, icon: icon(ListChecks) },
  { to: '/plan', label: copy.nav.plan, icon: icon(CalendarBlank) },
  { to: '/ask', label: copy.nav.ask, icon: icon(Sparkle) },
];
const SETTINGS: NavDef = { to: '/settings', label: copy.nav.settings, icon: icon(GearSix) };

/** Screens where the month matters; elsewhere the month control is hidden, not just ignored. */
const MONTHLY = ['/', '/transactions', '/plan'];

/** Payments waiting for you, from statements and from your phone, counted once. */
function useNeedsYou(): number {
  const review = useReviewQueue();
  const inbox = useCaptureInbox();
  return (review.data?.total ?? 0) + (inbox.data?.pending_count ?? 0);
}

function NavItem({ item, count }: { item: NavDef; count?: number }) {
  const reduce = useReducedMotion();
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        cx(
          'relative flex h-10 items-center gap-3 rounded-control px-3 text-[14.5px] font-semibold transition-colors duration-fast',
          isActive ? 'text-ink' : 'text-ink-2 hover:text-ink',
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive ? (
            <motion.span
              layoutId="nav-pill"
              aria-hidden
              className="absolute inset-0 -z-10 rounded-control bg-surface-selected"
              transition={
                reduce ? { duration: 0 } : { type: 'spring', stiffness: 420, damping: 34 }
              }
            />
          ) : null}
          <span className={cx('flex', isActive ? 'text-brand' : 'text-ink-3')}>
            {item.icon(isActive)}
          </span>
          <span className="flex-1">{item.label}</span>
          {count ? (
            <span className="tabular flex h-[22px] min-w-[22px] items-center justify-center rounded-full bg-brand px-1.5 text-[12px] font-bold text-brand-ink">
              {count}
            </span>
          ) : null}
        </>
      )}
    </NavLink>
  );
}

function Logo({ size = 'lg' }: { size?: 'lg' | 'sm' }) {
  return (
    <Link
      to="/welcome"
      className="flex items-center gap-2.5 transition-opacity hover:opacity-80"
      title="Return to welcome page"
    >
      <span
        aria-hidden
        className="h-7 w-7 rounded-[10px] bg-brand shadow-[inset_0_-3px_0_var(--color-coral)]"
      />
      <span
        className={cx(
          'serif-light leading-none text-ink',
          size === 'lg' ? 'text-[26px]' : 'text-[22px]',
        )}
      >
        {copy.product}
      </span>
    </Link>
  );
}

function DataBadge() {
  const session = useSession();
  if (session.data?.data_source === 'synthetic_demo')
    return <Badge tone="neutral">{copy.demoData}</Badge>;
  if (session.data?.data_source === 'connected')
    return <Badge tone="positive">{copy.liveData}</Badge>;
  return null;
}

/** Ctrl+K (or Cmd+K) opens Ask from anywhere. */
function useAskShortcut() {
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        navigate('/ask');
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate]);
}

function Frame() {
  const session = useSession();
  const needsYou = useNeedsYou();
  const location = useLocation();
  const navigate = useNavigate();
  useAskShortcut();
  const showMonth = MONTHLY.some((p) =>
    p === '/' ? location.pathname === '/' : location.pathname.startsWith(p),
  );
  const onAsk = location.pathname.startsWith('/ask');

  return (
    <div className="relative isolate grid min-h-screen grid-cols-1 lg:grid-cols-[15.5rem_minmax(0,1fr)]">
      <LiquidBackdrop />
      <CaptureOverlay />
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-ink focus:px-3 focus:py-2 focus:text-ink-inverse"
      >
        {copy.nav.skip}
      </a>

      {/* Sidebar (laptop) */}
      <aside className="no-print sticky top-0 hidden h-screen flex-col gap-8 border-r border-hairline bg-surface/90 px-3 py-6 backdrop-blur-xl lg:flex">
        <div className="px-3">
          <Logo />
        </div>
        <nav aria-label="Main" className="isolate flex flex-col gap-1">
          {NAV.map((item) => (
            <NavItem
              key={item.to}
              item={item}
              count={item.to === '/review' ? needsYou : undefined}
            />
          ))}
          <div aria-hidden className="mx-3 my-3 h-px bg-hairline" />
          <NavItem item={SETTINGS} />
        </nav>
        <div className="mt-auto px-3">
          <DataBadge />
        </div>
      </aside>

      <div className="min-w-0 pb-20 lg:pb-0">
        {/* Top bar */}
        <header className="no-print sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-hairline bg-canvas/80 px-4 backdrop-blur-xl sm:px-8">
          <div className="lg:hidden">
            <Logo size="sm" />
          </div>
          {showMonth ? (
            <div className="hidden sm:block">
              <MonthSwitcher />
            </div>
          ) : null}
          <div className="ml-auto flex items-center gap-2">
            {!onAsk ? (
              <button
                type="button"
                onClick={() => navigate('/ask')}
                className="hidden h-10 min-w-[17rem] items-center gap-2.5 rounded-full border border-hairline bg-surface px-4 text-[13.5px] text-ink-3 shadow-[0_1px_2px_rgba(31,26,23,0.04)] transition-[border-color,box-shadow] duration-fast hover:border-agent/40 hover:shadow-[0_4px_16px_-6px_rgba(91,71,214,0.35)] md:flex"
              >
                <Sparkle size={15} weight="fill" aria-hidden className="text-agent" />
                <span className="flex-1 text-left">{copy.nav.askHint}</span>
                <kbd className="rounded-[6px] border border-hairline px-1.5 font-mono text-[11px] text-ink-3">
                  Ctrl K
                </kbd>
              </button>
            ) : null}
            <Link
              to="/settings"
              aria-label={copy.nav.settings}
              className="flex size-10 items-center justify-center rounded-full text-ink-2 hover:bg-surface-sunken lg:hidden"
            >
              <GearSix size={20} aria-hidden />
            </Link>
          </div>
        </header>
        {showMonth ? (
          <div className="no-print flex justify-center border-b border-hairline px-4 py-2 sm:hidden">
            <MonthSwitcher compact />
          </div>
        ) : null}

        <main id="content" tabIndex={-1} className="min-w-0 outline-none">
          {session.error instanceof ApiError ? (
            <div className="mx-auto max-w-xl p-10">
              <ErrorState
                code={session.error.code}
                message={
                  session.error.code === 'UNREACHABLE'
                    ? copy.common.backendDown
                    : session.error.code === 'UNAUTHORIZED'
                      ? copy.common.unauthorized
                      : session.error.message
                }
                onRetry={() => void session.refetch()}
              />
            </div>
          ) : (
            <Outlet />
          )}
        </main>
      </div>

      {/* Bottom bar (phone width) */}
      <nav
        aria-label="Main"
        className="no-print fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-hairline bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      >
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cx(
                'relative flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-semibold',
                isActive ? 'text-brand' : 'text-ink-3',
              )
            }
          >
            {({ isActive }) => (
              <>
                {item.icon(isActive)}
                {item.label}
                {item.to === '/review' && needsYou > 0 ? (
                  <span className="tabular absolute top-2 left-1/2 ml-2 flex h-4 min-w-4 items-center justify-center rounded-full bg-brand px-1 text-[10px] font-bold text-brand-ink">
                    {needsYou}
                  </span>
                ) : null}
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

/** App frame: sidebar, top bar with the month and Ask, and the screen. */
export function Shell() {
  return (
    <MonthProvider>
      <Frame />
    </MonthProvider>
  );
}

/**
 * When a screen is shown inside another one's tab (Plan, Settings), its Page drops its own title
 * and outer spacing: the tab already names it.
 */
const EmbeddedContext = createContext(false);
export function Embedded({ children }: { children: ReactNode }) {
  return <EmbeddedContext.Provider value>{children}</EmbeddedContext.Provider>;
}

/** Standard page frame: serif title, optional lead, at most one main action, content. */
export function Page({
  title,
  lead,
  actions,
  children,
  wide = false,
}: {
  title: ReactNode;
  lead?: string;
  actions?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}) {
  const embedded = useContext(EmbeddedContext);
  if (embedded) {
    return (
      <div className="flex flex-col gap-5">
        {actions ? <div className="flex flex-wrap justify-end gap-2">{actions}</div> : null}
        {children}
      </div>
    );
  }
  return (
    <div
      className={cx(
        'mx-auto w-full px-5 py-8 sm:px-8 lg:py-10',
        wide ? 'max-w-[88rem]' : 'max-w-[76rem]',
      )}
    >
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="serif-light text-[34px] tracking-[-0.01em] sm:text-[44px]">{title}</h1>
          {lead ? <p className="mt-2 text-body text-ink-2">{lead}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}
