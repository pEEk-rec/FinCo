import { useMemo } from 'react';
import { Link } from 'react-router';

import { Button } from '../components/Button';
import { Constellation, type ClusterSpec, type ParticleSpec } from '../constellation/Constellation';
import { copy } from '../copy/en';

/** Restrained entry page: no statistics, no testimonials; the ambient field carries no numbers. */
export function WelcomeScreen() {
  const clusters: ClusterSpec[] = useMemo(() => [], []);
  const particles: ParticleSpec[] = useMemo(
    () =>
      Array.from({ length: 90 }, (_, i) => ({
        id: `ambient-${i}`,
        state: 'unassigned' as const,
        clusterId: null,
      })),
    [],
  );
  return (
    <div className="relative grid min-h-screen grid-cols-1 overflow-hidden lg:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
      <div className="z-10 flex flex-col justify-between px-8 py-10 sm:px-14">
        <span className="serif-light text-[26px]">{copy.product}</span>
        <div className="max-w-xl py-16">
          <h1 className="serif-light text-[44px] leading-[1.05] tracking-[-0.02em] sm:text-[60px]">
            A calm <em>ledger</em> for a student budget.
          </h1>
          <p className="mt-6 max-w-md text-body text-ink-2">{copy.welcome.body}</p>
          <p className="mt-3 max-w-md text-body text-ink-2">{copy.welcome.cannot}</p>
          <div className="mt-8">
            <Link to="/">
              <Button variant="primary">{copy.welcome.cta}</Button>
            </Link>
          </div>
        </div>
        <span aria-hidden />
      </div>
      <div className="relative hidden lg:block" aria-hidden>
        <div className="absolute inset-0">
          <Constellation
            particles={particles}
            clusters={clusters}
            height={900}
            mode="ambient"
            ariaLabel=""
          />
        </div>
      </div>
    </div>
  );
}
