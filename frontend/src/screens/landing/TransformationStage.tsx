import { ArrowCounterClockwise, CheckCircle, Sparkle } from '@phosphor-icons/react';
import { useMemo, useState } from 'react';

import {
  Constellation,
  type ClusterSpec,
  type ParticleSpec,
} from '../../constellation/Constellation';
import { landingCopy } from '../../copy/landing';
import { formatINR } from '../../format/money';

type StageId = 'scattered' | 'sorted' | 'understood';

export function TransformationStage() {
  const [activeStage, setActiveStage] = useState<StageId>('sorted');
  const [selectedGuess, setSelectedGuess] = useState<string | null>(null);
  const [isConfirmed, setIsConfirmed] = useState(false);

  // Clusters definition for sorted & understood stages
  const clusters: ClusterSpec[] = useMemo(
    () => [
      { id: 'c-food', label: 'Food & Dining', hue: 0, countText: '14' }, // figures-ok: illustrative landing example
      { id: 'c-rent', label: 'Rent & Housing', hue: 1, countText: '1' }, // figures-ok: illustrative landing example
      { id: 'c-travel', label: 'Transit & Auto', hue: 2, countText: '8' }, // figures-ok: illustrative landing example
      { id: 'c-bills', label: 'Bills & Recharges', hue: 4, countText: '3' }, // figures-ok: illustrative landing example
      { id: 'c-savings', label: 'Savings Deposit', hue: 10, countText: '2' }, // figures-ok: illustrative landing example
      { id: 'c-review', label: 'Needs you', hue: 5, isReview: true, countText: '1' }, // figures-ok: illustrative landing example
    ],
    [],
  );

  // Dynamic particle assignment based on stage
  const particles: ParticleSpec[] = useMemo(() => {
    const total = 64;
    return Array.from({ length: total }, (_, i) => {
      const id = `trans-p-${i}`;
      if (activeStage === 'scattered') {
        return { id, state: 'unassigned' as const, clusterId: null };
      }

      // Map into clusters
      if (i === 0) {
        return { id, state: 'review' as const, clusterId: 'c-review' };
      }
      if (i % 5 === 0) {
        return { id, state: 'ai' as const, clusterId: 'c-food' };
      }
      if (i % 5 === 1) {
        return { id, state: 'rule' as const, clusterId: 'c-travel' };
      }
      if (i % 5 === 2) {
        return { id, state: 'rule' as const, clusterId: 'c-rent' };
      }
      if (i % 5 === 3) {
        return { id, state: 'ai' as const, clusterId: 'c-bills' };
      }
      return { id, state: 'rule' as const, clusterId: 'c-savings' };
    });
  }, [activeStage]);

  const handleSelectGuess = (guess: string) => {
    setSelectedGuess(guess);
    setIsConfirmed(true);
  };

  const handleUndo = () => {
    setSelectedGuess(null);
    setIsConfirmed(false);
  };

  // Illustrative amount formatted cleanly without hardcoded strings
  const sampleAmountPaise = 25000; // figures-ok: illustrative landing example
  const formattedAmount = formatINR(sampleAmountPaise, { paise: 'never' });

  return (
    <section
      id="transformation"
      className="relative w-full py-20 lg:py-28 px-6 sm:px-12 lg:px-16 bg-[#FBF6F2] text-[#1F1A17] border-b border-[#EADFD7]"
    >
      <div className="mx-auto max-w-6xl">
        {/* Section Header */}
        <div className="text-center max-w-2xl mx-auto mb-12">
          <span className="label-mono text-[11px] text-[#BA3A25] tracking-widest uppercase">
            {landingCopy.transformation.badge}
          </span>
          <h2 className="landing-serif font-serif font-light text-[34px] sm:text-[46px] leading-[1.12] tracking-[-0.02em] mt-3">
            {landingCopy.transformation.title}
          </h2>
          <p className="mt-4 text-[16px] text-[#4F4540] leading-relaxed font-light">
            {landingCopy.transformation.description}
          </p>

          {/* Interactive Stage Switcher Pills */}
          <div className="mt-8 inline-flex p-1.5 rounded-full bg-[#F4ECE6] border border-[#EADFD7] shadow-inner">
            {landingCopy.transformation.stages.map((st, idx) => {
              const active = activeStage === st.id;
              return (
                <button
                  key={st.id}
                  type="button"
                  onClick={() => setActiveStage(st.id as StageId)}
                  className={`flex items-center gap-2 px-5 py-2 rounded-full text-[13px] font-semibold transition-all ${
                    active
                      ? 'bg-white text-[#1F1A17] shadow-md border border-[#EADFD7]'
                      : 'text-[#6B605A] hover:text-[#1F1A17]'
                  }`}
                >
                  <span
                    className={`h-2 w-2 rounded-full ${active ? 'bg-[#BA3A25]' : 'bg-[#D9C8BD]'}`}
                  />
                  <span>{`${idx + 1}. ${st.label}`}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* The Live Interactive Canvas Stage */}
        <div className="relative rounded-3xl border border-[#EADFD7] bg-white p-4 sm:p-8 shadow-sm overflow-hidden">
          {/* Top Status Bar of the Stage */}
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#F4ECE6] pb-4 mb-4 text-[13px]">
            <div className="flex items-center gap-2.5">
              <span className="inline-block h-2.5 w-2.5 rounded-full bg-emerald-500" />
              <span className="font-semibold text-[#1F1A17]">
                {activeStage === 'scattered' && 'Stage 1: Raw Unassigned Inflow'}
                {activeStage === 'sorted' && 'Stage 2: Deterministic Categorisation'}
                {activeStage === 'understood' && 'Stage 3: One-Tap In-the-Moment Review'}
              </span>
            </div>

            <div className="flex items-center gap-2 text-[#6B605A]">
              <Sparkle size={15} className="text-[#5B47D6]" />
              <span>Real-time preview</span>
            </div>
          </div>

          {/* Visualization Area */}
          <div className="relative h-[420px] sm:h-[480px] w-full rounded-2xl bg-[#FBF6F2] overflow-hidden flex items-center justify-center">
            {/* Constellation Particle Engine */}
            <div className="absolute inset-0">
              <Constellation
                particles={particles}
                clusters={activeStage === 'scattered' ? [] : clusters}
                height={480}
                mode={activeStage === 'scattered' ? 'ambient' : 'pipeline'}
                ariaLabel="Interactive transaction categorisation pipeline visualization"
              />
            </div>

            {/* Overlaid Interactive Card when in 'understood' stage */}
            {activeStage === 'understood' && (
              <div className="relative z-20 max-w-sm w-full mx-4 rounded-2xl border border-[#BA3A25]/30 bg-white p-5 shadow-xl transition-all animate-in fade-in zoom-in-95 duration-300">
                <div className="flex items-center justify-between">
                  <span className="rounded bg-[#FDECE7] px-2 py-0.5 text-[11px] font-bold tracking-wider text-[#BA3A25] uppercase">
                    {landingCopy.transformation.interactivePrompt.tag}
                  </span>
                  <span className="text-[12px] font-medium text-[#6B605A]">Just now via UPI</span>
                </div>

                <div className="mt-3">
                  <div className="text-[24px] font-extrabold tracking-tight text-[#1F1A17]">
                    {formattedAmount}
                  </div>
                  <div className="text-[14px] text-[#4F4540]">
                    To {landingCopy.transformation.interactivePrompt.merchant}
                  </div>
                </div>

                <p className="mt-3 text-[13px] font-medium text-[#1F1A17]">
                  {landingCopy.transformation.interactivePrompt.query}
                </p>

                {/* Guess chips */}
                {!isConfirmed ? (
                  <div className="mt-3 flex flex-col gap-2">
                    {landingCopy.transformation.interactivePrompt.guesses.map((g) => (
                      <button
                        key={g}
                        type="button"
                        onClick={() => handleSelectGuess(g)}
                        className="flex items-center justify-between rounded-xl border border-[#EADFD7] bg-[#FDF8F5] px-3.5 py-2 text-left text-[13px] font-medium text-[#1F1A17] hover:border-[#BA3A25] hover:bg-[#FDECE7] transition-colors"
                      >
                        <span>{g}</span>
                        <span className="text-[11px] font-bold text-[#BA3A25]">Choose</span>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3.5 text-center">
                    <div className="flex items-center justify-center gap-1.5 text-[13px] font-semibold text-emerald-800">
                      <CheckCircle size={17} weight="fill" className="text-emerald-600" />
                      <span>{selectedGuess}</span>
                    </div>
                    <p className="mt-1 text-[12px] text-emerald-700">
                      {landingCopy.transformation.interactivePrompt.confirmedText}
                    </p>
                    <button
                      type="button"
                      onClick={handleUndo}
                      className="mt-2.5 inline-flex items-center gap-1.5 text-[12px] font-semibold text-[#BA3A25] hover:underline"
                    >
                      <ArrowCounterClockwise size={13} />
                      <span>Undo selection</span>
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Explanatory Narrative for Active Stage */}
          <div className="mt-6 rounded-2xl bg-[#FBF6F2] p-5 sm:p-6 border border-[#EADFD7]">
            {landingCopy.transformation.stages.map((st) => {
              if (st.id !== activeStage) return null;
              return (
                <div
                  key={st.id}
                  className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
                >
                  <div>
                    <h3 className="font-serif font-normal text-[21px] text-[#1F1A17]">
                      {st.headline}
                    </h3>
                    <p className="mt-1 text-[14px] text-[#4F4540] font-light">{st.body}</p>
                  </div>
                  <div className="shrink-0">
                    <span className="text-[12px] font-bold text-[#BA3A25] tracking-wider uppercase">
                      {st.label}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}
