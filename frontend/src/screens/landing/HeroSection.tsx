import { Link } from 'react-router';

import { landingCopy } from '../../copy/landing';
import { HeroVideo } from './HeroVideo';

/** Delay the entrance of each line a little, so the page settles rather than appears. */
const enter = (n: number) => ({ animationDelay: `${150 + n * 140}ms` });

/**
 * The whole landing page: a figure above the clouds, and the few words that matter, in one left
 * column that never moves around: the name, the promise, one button, three plain points.
 */
export function HeroSection() {
  const { titleMain, titleAccent, line, ctaPrimary, points } = landingCopy.hero;
  return (
    <header className="relative h-svh min-h-[34rem] w-full overflow-hidden bg-[#0D0B0A] text-white">
      <HeroVideo />

      {/* Shade the left for the words and the very bottom for the points; the figure stays clear. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_50%_60%,rgba(10,8,14,0)_35%,rgba(10,8,14,0.3)_100%)]"
      />

      <Link
        to="/welcome"
        className="serif-light absolute left-6 top-6 z-20 flex items-center gap-2.5 text-[28px] leading-none text-white sm:left-12 sm:top-8 lg:left-16"
        aria-label="FinCo"
      >
        <span
          aria-hidden
          className="h-7 w-7 rounded-full border-2 border-white bg-coral shadow-[2px_2px_0_rgba(255,255,255,0.85)]"
        />
        FinCo
      </Link>

      <main className="relative z-10 flex h-full flex-col justify-start px-6 pt-28 sm:px-12 md:justify-center md:pt-0 lg:px-16">
        <div className="max-w-[34rem]">
          <h1
            className="serif-light rise text-[46px] leading-[0.98] md:text-[56px] lg:text-[84px]"
            style={enter(0)}
          >
            {titleMain} <br />
            <em className="!text-[#FFB68C]">{titleAccent}</em>
          </h1>
          <p
            className="rise mt-5 text-[19px] font-medium leading-snug text-white/90 md:text-[22px] lg:text-[26px]"
            style={enter(1)}
          >
            {line}
          </p>
          <div className="rise mt-8" style={enter(2)}>
            <Link
              to="/"
              className="pop inline-flex h-14 items-center rounded-control bg-coral px-8 text-[16px] font-bold text-ink [--edge:var(--color-brand-edge)]"
            >
              {ctaPrimary}
            </Link>
          </div>
          <ul
            className="rise mt-8 flex w-[min(44rem,88vw)] flex-col gap-2 text-[14px] text-white/85 sm:flex-row sm:flex-wrap sm:gap-x-6"
            style={enter(3)}
          >
            {points.map((p) => (
              <li key={p} className="flex items-center gap-2">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-[#FFB68C]" />
                {p}
              </li>
            ))}
          </ul>
        </div>
      </main>
    </header>
  );
}
