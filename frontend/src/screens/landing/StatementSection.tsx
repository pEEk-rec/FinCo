import { landingCopy } from '../../copy/landing';

export function StatementSection() {
  return (
    <section className="relative w-full py-20 lg:py-28 px-6 sm:px-12 lg:px-16 bg-[#FBF6F2] border-b border-[#EADFD7] text-center">
      <div className="mx-auto max-w-4xl">
        <span className="label-mono text-[11px] font-bold text-[#BA3A25] tracking-widest uppercase">
          {landingCopy.statement.badge}
        </span>

        <h2 className="landing-serif font-serif font-light text-[36px] sm:text-[54px] lg:text-[64px] leading-[1.12] tracking-[-0.02em] text-[#1F1A17] mt-4">
          {landingCopy.statement.headline}
        </h2>

        <p className="mt-6 mx-auto max-w-2xl text-[16px] sm:text-[18px] text-[#4F4540] leading-relaxed font-light">
          {landingCopy.statement.paragraph}
        </p>

        <div className="mt-10 flex items-center justify-center gap-6 text-[13px] text-[#6B605A]">
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-[#BA3A25]" />
            Immediate context
          </span>
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-[#0F7A5A]" />
            No backlog anxiety
          </span>
          <span className="flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-[#5B47D6]" />
            Quiet prompts only
          </span>
        </div>
      </div>
    </section>
  );
}
