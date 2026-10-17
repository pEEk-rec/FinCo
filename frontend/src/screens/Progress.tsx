import { Lock, Medal } from '@phosphor-icons/react';
import { motion } from 'motion/react';

import { ApiError } from '../api/client';
import { useCoach } from '../api/hooks';
import { Card } from '../components/Card';
import { Page } from '../components/Shell';
import { EmptyState, ErrorState, SkeletonBlock } from '../components/States';
import { formatDay } from '../format/date';
import { formatUnit } from '../format/metric';
import { LiquidVessel } from '../motion/Liquid';
import { NumberTicker } from '../motion/NumberTicker';
import { motion as tokens } from '../tokens/tokens';

const stamp = (iso: string) => formatDay(iso);

export function ProgressScreen() {
  const coach = useCoach();
  return (
    <Page
      title={
        <>
          Your progress, <em>kept honest</em>
        </>
      }
      lead="Points come only from things you actually did. Streaks forgive a missed day, and nothing here compares you with anyone but yourself."
    >
      {coach.isPending ? (
        <Card className="p-6">
          <SkeletonBlock lines={5} />
        </Card>
      ) : coach.error ? (
        <ErrorState
          code={coach.error instanceof ApiError ? coach.error.code : 'UNKNOWN'}
          message={coach.error.message}
          onRetry={() => void coach.refetch()}
        />
      ) : (
        (() => {
          const p = coach.data.progress;
          return (
            <div className="flex flex-col gap-10">
              <Card className="rise flex flex-wrap items-center gap-8 p-8">
                <LiquidVessel fraction={p.level.progress_bp / 10000} tone="gold" size={164}>
                  <span className="flex flex-col leading-none">
                    <span className="label-mono text-ink-3">Level</span>
                    <span className="serif-light mt-1 text-[56px]">{p.level.number}</span>
                  </span>
                </LiquidVessel>
                <div className="min-w-0">
                  <h2 className="serif-light text-[34px] leading-tight">{p.level.name}</h2>
                  <p className="tabular mt-2 text-[17px] text-ink-2">
                    <NumberTicker value={`${p.level.total_xp} points`} />
                    {p.level.xp_to_next !== null && p.level.xp_to_next !== undefined
                      ? `, ${p.level.xp_to_next} more to the next level`
                      : ', the top level'}
                  </p>
                </div>
              </Card>

              <section aria-labelledby="badges-title" className="rise">
                <h2 id="badges-title" className="serif-light mb-4 text-[26px]">
                  Badges
                </h2>
                <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                  {p.badges.map((b, i) => (
                    <motion.li
                      key={b.code}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.06, duration: tokens.base / 1000 }}
                    >
                      <Card className="glow-brand flex h-full gap-4 p-5">
                        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-brand-tint text-brand">
                          <Medal size={24} weight="fill" aria-hidden />
                        </span>
                        <div>
                          <h3 className="text-[16px] font-medium">{b.name}</h3>
                          <p className="text-small text-ink-2">{b.description}</p>
                          <p className="mt-1 text-small text-ink-3">{stamp(b.awarded_at)}</p>
                        </div>
                      </Card>
                    </motion.li>
                  ))}
                  {p.locked_badges.map((b) => (
                    <li key={b.code}>
                      <Card className="flex h-full gap-4 border-dashed p-5">
                        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-surface-sunken text-ink-3">
                          <Lock size={20} aria-hidden />
                        </span>
                        <div>
                          <h3 className="text-[16px] font-medium text-ink-2">{b.name}</h3>
                          <p className="text-small text-ink-3">{b.description}</p>
                        </div>
                      </Card>
                    </li>
                  ))}
                </ul>
              </section>

              <div className="grid gap-8 lg:grid-cols-2">
                <section aria-labelledby="streaks-title" className="rise">
                  <h2 id="streaks-title" className="serif-light mb-4 text-[26px]">
                    Streaks that forgive
                  </h2>
                  {p.streaks.length === 0 ? (
                    <Card className="p-6">
                      <EmptyState message="Streaks begin once you categorise payments or answer check-ins." />
                    </Card>
                  ) : (
                    <ul className="grid gap-3">
                      {p.streaks.map((s) => (
                        <li key={s.code}>
                          <Card className="flex items-center gap-4 p-4">
                            <LiquidVessel
                              fraction={Math.min(1, s.days / 30)}
                              tone="positive"
                              size={56}
                              shape="drop"
                            />
                            <div>
                              <p className="text-[15px]">{s.label}</p>
                              <p className="tabular text-small text-ink-3">
                                {s.days === 1 ? '1 day' : `${s.days} days`}
                              </p>
                            </div>
                          </Card>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>

                <section aria-labelledby="bests-title" className="rise">
                  <h2 id="bests-title" className="serif-light mb-4 text-[26px]">
                    Your own bests
                  </h2>
                  {p.bests.length === 0 ? (
                    <Card className="p-6">
                      <EmptyState message="Finish a challenge and your best result will be kept here." />
                    </Card>
                  ) : (
                    <ul className="grid gap-3">
                      {p.bests.map((b) => (
                        <li key={`${b.label}-${b.scope}-${b.window_days}`}>
                          <Card className="flex items-center justify-between gap-4 p-4">
                            <div className="min-w-0">
                              <p className="text-[15px] capitalize">{b.label}</p>
                              <p className="text-small text-ink-3">
                                Over {b.window_days} days, {stamp(b.achieved_at)}
                              </p>
                            </div>
                            <span className="tabular serif-light text-[28px] text-gold">
                              {formatUnit(b.unit, b.best)}
                            </span>
                          </Card>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              </div>
            </div>
          );
        })()
      )}
    </Page>
  );
}
