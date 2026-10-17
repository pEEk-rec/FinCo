import {
  ArrowsLeftRight,
  Clock,
  Broadcast,
  CloudArrowDown,
  FileText,
  ListChecks,
  Sparkle,
  SquaresFour,
  Target,
  Trophy,
  Flask,
} from '@phosphor-icons/react';
import type { ReactNode } from 'react';
import { motion } from 'motion/react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router';

import { useReviewQueue, useSession } from '../api/hooks';
import { ApiError } from '../api/client';
import { copy } from '../copy/en';
import { Badge } from './Badge';
import { cx } from './cx';
import { LiquidBackdrop } from '../motion/LiquidBackdrop';
import { ErrorState } from './States';

const NAV: { to: string; label: string; icon: ReactNode; end?: boolean }[] = [
  { to: '/', label: copy.nav.dashboard, icon: <SquaresFour size={18} />, end: true },
  { to: '/transactions', label: copy.nav.transactions, icon: <ArrowsLeftRight size={18} /> },
  { to: '/review', label: copy.nav.review, icon: <ListChecks size={18} /> },
  { to: '/goals', label: copy.nav.goals, icon: <Target size={18} /> },
  { to: '/challenges', label: copy.nav.challenges, icon: <Flask size={18} /> },
  { to: '/progress', label: copy.nav.progress, icon: <Trophy size={18} /> },
  { to: '/monthly', label: copy.nav.monthly, icon: <FileText size={18} /> },
  { to: '/connect', label: copy.nav.connect, icon: <CloudArrowDown size={18} /> },
];

function NavItem({
  to,
  label,
  icon,
  end,
  count,
  active,
}: (typeof NAV)[number] & { count?: number; active?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cx(
          'relative flex h-9 items-center gap-3 rounded-control px-3 text-[14px] transition-colors duration-fast',
          (active ?? isActive) ? 'font-medium text-brand' : 'text-ink-2 hover:text-ink',
        )
      }
    >
      {({ isActive }) => (
        <>
          {(active ?? isActive) ? (
            // One shared blob that flows from item to item (a spring, so it settles like liquid).
            <motion.span
              layoutId="nav-liquid"
              aria-hidden
              className="absolute inset-0 -z-10 rounded-control bg-brand-tint ring-1 ring-coral/35 ring-inset"
              transition={{ type: 'spring', stiffness: 380, damping: 30 }}
            />
          ) : null}
          <span
            aria-hidden
            className={cx('flex', (active ?? isActive) ? 'text-brand' : 'text-ink-3')}
          >
            {icon}
          </span>
          <span className="flex-1">{label}</span>
          {count ? <span className="tabular text-small text-ink-3">{count}</span> : null}
        </>
      )}
    </NavLink>
  );
}

/** App frame: left navigation with Ask pinned at the bottom, and the content area. */
export function Shell() {
  const session = useSession();
  const review = useReviewQueue();
  const navigate = useNavigate();
  const location = useLocation();
  const onAgent = location.pathname.startsWith('/agent');
  const onActivity = onAgent && location.hash === '#activity';

  return (
    <div className="relative isolate grid min-h-screen grid-cols-1 lg:grid-cols-[15rem_minmax(0,1fr)]">
      <LiquidBackdrop />
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded-control focus:bg-ink focus:px-3 focus:py-2 focus:text-ink-inverse"
      >
        {copy.nav.skip}
      </a>
      <aside className="no-print glass sticky top-0 hidden h-screen flex-col rounded-none border-y-0 border-l-0 px-3 py-5 lg:flex">
        <div className="mb-8 flex items-center gap-2.5 px-3">
          <span
            aria-hidden
            className="h-6 w-6 rounded-full bg-[conic-gradient(from_200deg,var(--color-coral),var(--color-peach),var(--color-brand),var(--color-coral))] shadow-[0_0_18px_-4px_var(--color-coral)]"
          />
          <span className="serif-light text-[26px] leading-none">{copy.product}</span>
        </div>
        <nav aria-label="Main" className="isolate flex flex-col gap-0.5">
          {NAV.map((item) => (
            <NavItem
              key={item.to}
              {...item}
              count={item.to === '/review' ? review.data?.total : undefined}
            />
          ))}
          {session.data?.data_source === 'connected' ? (
            <NavItem to="/live" label={copy.nav.live} icon={<Broadcast size={18} />} />
          ) : null}
          <NavItem
            to="/agent"
            label={copy.nav.agent}
            icon={<Sparkle size={18} />}
            active={onAgent && !onActivity}
          />
          <NavItem
            to="/agent#activity"
            label={copy.nav.timeline}
            icon={<Clock size={18} />}
            active={onActivity}
          />
        </nav>
        <div className="mt-auto flex flex-col gap-3">
          {session.data?.data_source === 'synthetic_demo' ? (
            <Badge tone="neutral" className="self-start">
              {copy.demoData}
            </Badge>
          ) : session.data?.data_source === 'connected' ? (
            <Badge tone="positive" className="self-start">
              {copy.liveData}
            </Badge>
          ) : null}
          <button
            type="button"
            onClick={() => navigate('/agent')}
            className="flex h-10 items-center gap-2 rounded-control border border-hairline bg-surface px-3 text-[14px] text-agent transition-colors duration-fast hover:border-agent"
          >
            <Sparkle size={16} weight="fill" aria-hidden />
            {copy.nav.ask}
          </button>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="no-print flex h-14 items-center justify-between border-b border-hairline px-4 lg:hidden">
          <span className="serif-light text-[22px]">{copy.product}</span>
          <nav aria-label="Main" className="flex gap-1 overflow-x-auto">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                aria-label={item.label}
                className={({ isActive }) =>
                  cx(
                    'rounded-control p-2',
                    isActive ? 'bg-surface-selected text-ink' : 'text-ink-3',
                  )
                }
              >
                {item.icon}
              </NavLink>
            ))}
            <NavLink
              to="/agent"
              aria-label={copy.nav.agent}
              className="rounded-control p-2 text-agent"
            >
              <Sparkle size={18} />
            </NavLink>
          </nav>
        </header>
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
    </div>
  );
}

/** Standard page frame: serif title, optional lead, content. */
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
  return (
    <div
      className={cx(
        'mx-auto w-full px-5 py-8 sm:px-8 lg:py-10',
        wide ? 'max-w-[88rem]' : 'max-w-[76rem]',
      )}
    >
      <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <h1 className="serif-light text-[32px] leading-[1.15] sm:text-[36px]">{title}</h1>
          {lead ? <p className="mt-2 text-body text-ink-2">{lead}</p> : null}
        </div>
        {actions}
      </div>
      {children}
    </div>
  );
}
