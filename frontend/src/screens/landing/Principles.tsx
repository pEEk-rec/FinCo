import { CheckCircle, ShieldCheck, Sparkle, UserCheck } from '@phosphor-icons/react';

import { landingCopy } from '../../copy/landing';

export function Principles() {
  const icons = [
    <ShieldCheck key="p1" size={24} weight="duotone" className="text-[#0F7A5A]" />,
    <Sparkle key="p2" size={24} weight="duotone" className="text-[#5B47D6]" />,
    <UserCheck key="p3" size={24} weight="duotone" className="text-[#BA3A25]" />,
    <CheckCircle key="p4" size={24} weight="duotone" className="text-[#9A600A]" />,
  ];

  return (
    <section
      id="principles"
      className="relative w-full py-20 lg:py-28 px-6 sm:px-12 lg:px-16 bg-[#FBF6F2] border-b border-[#EADFD7]"
    >
      <div className="mx-auto max-w-6xl">
        <div className="text-center max-w-xl mx-auto mb-16">
          <span className="label-mono text-[11px] text-[#BA3A25] tracking-widest uppercase">
            {landingCopy.principles.badge}
          </span>
          <h2 className="landing-serif font-serif font-light text-[34px] sm:text-[46px] leading-[1.12] tracking-[-0.02em] text-[#1F1A17] mt-3">
            {landingCopy.principles.title}
          </h2>
        </div>

        {/* 4 Columns */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8">
          {landingCopy.principles.items.map((item, idx) => (
            <div
              key={item.label}
              className="flex flex-col justify-between rounded-3xl border border-[#EADFD7] bg-white p-7 shadow-sm hover:border-[#D9C8BD] transition-all"
            >
              <div>
                <div className="mb-5">{icons[idx]}</div>
                <span className="label-mono text-[11px] font-bold text-[#6B605A] tracking-wider uppercase">
                  {item.label}
                </span>
                <h3 className="font-serif font-normal text-[22px] text-[#1F1A17] mt-1.5">
                  {item.title}
                </h3>
                <p className="mt-3 text-[14px] text-[#4F4540] leading-relaxed font-light">
                  {item.body}
                </p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
