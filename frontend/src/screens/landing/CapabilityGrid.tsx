import {
  CaretDown,
  CaretUp,
  CheckCircle,
  Eye,
  Lightning,
  Lock,
  Sparkle,
  TrendUp,
} from '@phosphor-icons/react';
import { useState } from 'react';

import { landingCopy } from '../../copy/landing';
import { formatINR } from '../../format/money';

export function CapabilityGrid() {
  // State for Card 1 (Interactive Tagging)
  const [activeChoice, setActiveChoice] = useState<string | null>(null);

  // State for Card 2 (Show reasoning accordion)
  const [isEvidenceExpanded, setIsEvidenceExpanded] = useState(false);

  // State for Card 4 (Goal progress slider)
  const [goalPercent, setGoalPercent] = useState(68); // figures-ok: illustrative landing example

  const sampleCard1Amount = formatINR(18000, { paise: 'never' }); // figures-ok: illustrative landing example
  const sampleCard3Rent = formatINR(450000, { paise: 'never' }); // figures-ok: illustrative landing example

  return (
    <section
      id="capabilities"
      className="relative w-full py-20 lg:py-28 px-6 sm:px-12 lg:px-16 bg-[#FBF6F2] border-b border-[#EADFD7]"
    >
      <div className="mx-auto max-w-6xl">
        {/* Section Header */}
        <div className="max-w-2xl mb-14">
          <span className="label-mono text-[11px] text-[#BA3A25] tracking-widest uppercase">
            {landingCopy.capabilities.badge}
          </span>
          <h2 className="landing-serif font-serif font-light text-[34px] sm:text-[46px] leading-[1.12] tracking-[-0.02em] text-[#1F1A17] mt-3">
            {landingCopy.capabilities.title}
          </h2>
        </div>

        {/* Bento Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {/* Card 1: Asks only when unsure */}
          <div className="rounded-3xl border border-[#EADFD7] bg-white p-7 shadow-sm flex flex-col justify-between hover:border-[#D9C8BD] transition-all">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="label-mono rounded bg-[#FDECE7] px-2.5 py-0.5 text-[11px] text-[#BA3A25] uppercase">
                  Example
                </span>
                <span className="text-[12px] font-semibold text-[#6B605A]">In-moment prompt</span>
              </div>
              <h3 className="font-serif font-normal text-[22px] text-[#1F1A17]">
                {landingCopy.capabilities.cards[0]?.title}
              </h3>
              <p className="mt-2 text-[14px] text-[#4F4540] leading-relaxed font-light">
                {landingCopy.capabilities.cards[0]?.description}
              </p>
            </div>

            {/* Micro-interactive prompt */}
            <div className="mt-6 rounded-2xl border border-[#EADFD7] bg-[#FBF6F2] p-4">
              <div className="flex items-center justify-between text-[13px]">
                <span className="font-bold text-[#1F1A17]">{sampleCard1Amount} to Campus Cafe</span>
                <span className="text-[11px] text-[#6B605A]">UPI</span>
              </div>
              <p className="mt-2 text-[12px] text-[#4F4540]">Assign this payment:</p>
              <div className="mt-2.5 flex flex-wrap gap-1.5">
                {['Meals', 'Coffee run', 'Group split'].map((label) => {
                  const isSelected = activeChoice === label;
                  return (
                    <button
                      key={label}
                      type="button"
                      onClick={() => setActiveChoice(isSelected ? null : label)}
                      className={`rounded-full px-3 py-1 text-[12px] font-medium transition-all ${
                        isSelected
                          ? 'bg-[#0F7A5A] text-white shadow-sm'
                          : 'bg-white border border-[#EADFD7] text-[#1F1A17] hover:bg-[#FDECE7]'
                      }`}
                    >
                      {isSelected ? `✓ ${label}` : label}
                    </button>
                  );
                })}
              </div>
              {activeChoice && (
                <div className="mt-2.5 text-[11px] text-[#0F7A5A] font-semibold flex items-center gap-1">
                  <CheckCircle size={13} weight="fill" />
                  <span>Rule recorded for next time</span>
                </div>
              )}
            </div>
          </div>

          {/* Card 2: Shows its reasoning */}
          <div className="rounded-3xl border border-[#EADFD7] bg-white p-7 shadow-sm flex flex-col justify-between hover:border-[#D9C8BD] transition-all">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="label-mono rounded bg-[#ECE8FD] px-2.5 py-0.5 text-[11px] text-[#5B47D6] uppercase">
                  Example
                </span>
                <span className="text-[12px] font-semibold text-[#5B47D6] flex items-center gap-1">
                  <Sparkle size={13} />
                  <span>Traceable</span>
                </span>
              </div>
              <h3 className="font-serif font-normal text-[22px] text-[#1F1A17]">
                {landingCopy.capabilities.cards[1]?.title}
              </h3>
              <p className="mt-2 text-[14px] text-[#4F4540] leading-relaxed">
                {landingCopy.capabilities.cards[1]?.description}
              </p>
            </div>

            {/* Micro-interactive reasoning accordion */}
            <div className="mt-6 rounded-2xl border border-[#EADFD7] bg-[#FBF6F2] p-4">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-bold text-[#1F1A17]">Metro Smart Card</span>
                <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-[#0F7A5A]">
                  High confidence
                </span>
              </div>
              <button
                type="button"
                onClick={() => setIsEvidenceExpanded(!isEvidenceExpanded)}
                className="mt-3 flex w-full items-center justify-between text-[12px] font-semibold text-[#5B47D6] hover:underline"
              >
                <span>{isEvidenceExpanded ? 'Hide details' : 'Inspect source rule'}</span>
                {isEvidenceExpanded ? <CaretUp size={13} /> : <CaretDown size={13} />}
              </button>
              {isEvidenceExpanded && (
                <div className="mt-2.5 pt-2 border-t border-[#EADFD7] text-[11px] text-[#4F4540] space-y-1">
                  <div>• VPA matches transit gate recurring pattern</div>
                  <div>• Consistent with prior Friday commute rhythms</div>
                  <div>• Zero ambiguity: automatically classified to Transit</div>
                </div>
              )}
            </div>
          </div>

          {/* Card 3: Sees what is coming */}
          <div className="rounded-3xl border border-[#EADFD7] bg-white p-7 shadow-sm flex flex-col justify-between hover:border-[#D9C8BD] transition-all">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="label-mono rounded bg-[#FBF0DA] px-2.5 py-0.5 text-[11px] text-[#9A600A] uppercase">
                  Example
                </span>
                <span className="text-[12px] font-semibold text-[#9A600A]">Pace projection</span>
              </div>
              <h3 className="font-serif font-normal text-[22px] text-[#1F1A17]">
                {landingCopy.capabilities.cards[2]?.title}
              </h3>
              <p className="mt-2 text-[14px] text-[#4F4540] leading-relaxed">
                {landingCopy.capabilities.cards[2]?.description}
              </p>
            </div>

            {/* Trajectory micro-chart */}
            <div className="mt-6 rounded-2xl border border-[#EADFD7] bg-[#FBF6F2] p-4">
              <div className="flex justify-between items-center text-[12px]">
                <span className="font-semibold text-[#1F1A17]">Trajectory vs Budget</span>
                <span className="text-[11px] text-[#0F7A5A] font-bold">On pace</span>
              </div>
              <svg className="w-full h-12 mt-2" viewBox="0 0 200 48" aria-hidden="true">
                {/* Budget ceiling line */}
                <line
                  x1="0"
                  y1="12"
                  x2="200"
                  y2="12"
                  stroke="#D9C8BD"
                  strokeDasharray="3 3"
                  strokeWidth="1"
                />
                {/* Confidence band */}
                <path
                  d="M 0 38 Q 60 30 120 24 T 200 16 L 200 32 Q 140 38 80 42 Z"
                  fill="#E2F3EC"
                  opacity="0.8"
                />
                {/* Actual spending curve */}
                <path d="M 0 42 Q 50 36 100 28" fill="none" stroke="#0F7A5A" strokeWidth="2.5" />
                <circle cx="100" cy="28" r="3.5" fill="#0F7A5A" />
              </svg>
              <div className="mt-2 flex items-center justify-between text-[11px] text-[#6B605A]">
                <span>Rent committed ({sampleCard3Rent})</span>
                <span className="text-[#975300] font-semibold">in four days</span>
              </div>
            </div>
          </div>

          {/* Card 4: Your goals, your pace */}
          <div className="rounded-3xl border border-[#EADFD7] bg-white p-7 shadow-sm flex flex-col justify-between hover:border-[#D9C8BD] transition-all">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="label-mono rounded bg-[#FDECE7] px-2.5 py-0.5 text-[11px] text-[#BA3A25] uppercase">
                  Example
                </span>
                <span className="text-[12px] font-semibold text-[#BA3A25]">Living goals</span>
              </div>
              <h3 className="font-serif font-normal text-[22px] text-[#1F1A17]">
                {landingCopy.capabilities.cards[3]?.title}
              </h3>
              <p className="mt-2 text-[14px] text-[#4F4540] leading-relaxed">
                {landingCopy.capabilities.cards[3]?.description}
              </p>
            </div>

            {/* Interactive Goal Progress Bar */}
            <div className="mt-6 rounded-2xl border border-[#EADFD7] bg-[#FBF6F2] p-4">
              <div className="flex justify-between items-center text-[12px] font-bold text-[#1F1A17]">
                <span>Emergency Buffer Fund</span>
                <span className="text-[#BA3A25] tabular">{goalPercent}%</span>
              </div>
              <div className="mt-2 h-2.5 w-full rounded-full bg-[#EADFD7] overflow-hidden">
                <div
                  className="h-full bg-[#BA3A25] transition-all duration-300"
                  style={{ width: `${goalPercent}%` }}
                />
              </div>
              <div className="mt-3 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setGoalPercent((p) => Math.max(10, p - 10))} // figures-ok: illustrative landing example
                  className="rounded-lg bg-white border border-[#EADFD7] px-2.5 py-1 text-[11px] font-medium text-[#1F1A17] hover:bg-[#F4ECE6]"
                >
                  Simulate withdrawal
                </button>
                <button
                  type="button"
                  onClick={() => setGoalPercent((p) => Math.min(100, p + 10))} // figures-ok: illustrative landing example
                  className="rounded-lg bg-white border border-[#EADFD7] px-2.5 py-1 text-[11px] font-medium text-[#BA3A25] hover:bg-[#FDECE7]"
                >
                  Simulate deposit
                </button>
              </div>
            </div>
          </div>

          {/* Card 5: Learns what helps you */}
          <div className="rounded-3xl border border-[#EADFD7] bg-white p-7 shadow-sm flex flex-col justify-between hover:border-[#D9C8BD] transition-all">
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="label-mono rounded bg-emerald-50 px-2.5 py-0.5 text-[11px] text-[#0F7A5A] uppercase">
                  Example
                </span>
                <span className="text-[12px] font-semibold text-[#0F7A5A] flex items-center gap-1">
                  <TrendUp size={13} />
                  <span>Honest comparison</span>
                </span>
              </div>
              <h3 className="font-serif font-normal text-[22px] text-[#1F1A17]">
                {landingCopy.capabilities.cards[4]?.title}
              </h3>
              <p className="mt-2 text-[14px] text-[#4F4540] leading-relaxed">
                {landingCopy.capabilities.cards[4]?.description}
              </p>
            </div>

            {/* Experiment observation note */}
            <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50/70 p-4 text-[12px] text-[#1F1A17]">
              <div className="font-bold text-[#0F7A5A]">Observed Spending Pattern</div>
              <p className="mt-1 text-[#4F4540] leading-normal font-light">
                Discretionary food spend settled lower than earlier weeks after you set daily dining
                caps.
              </p>
              <div className="mt-2 flex items-center gap-1 text-[11px] text-[#6B605A]">
                <Eye size={12} />
                <span>Zero unsolicited financial lectures</span>
              </div>
            </div>
          </div>

          {/* Card 6: Never moves your money */}
          <div
            id="safeguards"
            className="rounded-3xl border border-[#D9C8BD] bg-[#FDF8F5] p-7 shadow-sm flex flex-col justify-between hover:border-[#BA3A25] transition-all"
          >
            <div>
              <div className="flex items-center justify-between mb-4">
                <span className="label-mono rounded bg-[#FDECE7] px-2.5 py-0.5 text-[11px] font-bold text-[#BA3A25] uppercase">
                  {landingCopy.capabilities.cards[5]?.tag}
                </span>
                <span className="text-[12px] font-semibold text-[#BA3A25] flex items-center gap-1">
                  <Lock size={13} weight="fill" />
                  <span>Air-gapped safety</span>
                </span>
              </div>
              <h3 className="font-serif font-normal text-[22px] text-[#1F1A17]">
                {landingCopy.capabilities.cards[5]?.title}
              </h3>
              <p className="mt-2 text-[14px] text-[#4F4540] leading-relaxed">
                {landingCopy.capabilities.cards[5]?.description}
              </p>
            </div>

            {/* Verified Statement Box */}
            <div className="mt-6 rounded-2xl border border-[#BA3A25]/30 bg-white p-4">
              <div className="flex items-center gap-2 text-[13px] font-bold text-[#BA3A25]">
                <Lightning size={15} weight="fill" />
                <span>Zero Execution Privilege</span>
              </div>
              <p className="mt-1.5 text-[12px] text-[#4F4540] leading-normal">
                FinCo operates with read-only statement ingestion. It cannot trigger debit
                transfers, request OTPs, or initiate payment flows under any scenario.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
