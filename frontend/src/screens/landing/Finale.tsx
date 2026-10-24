import { ArrowRight, Sparkle } from '@phosphor-icons/react';
import { Link } from 'react-router';

import { landingCopy } from '../../copy/landing';

export function Finale() {
  return (
    <section className="relative w-full overflow-hidden bg-[#0D0B0A] py-28 sm:py-36 px-6 sm:px-12 lg:px-16 text-white text-center">
      {/* 1. Slow Aurora Fluid Glow Background */}
      <div className="absolute inset-0 pointer-events-none overflow-hidden" aria-hidden="true">
        {/* Blob 1: Coral / Amber */}
        <div className="aurora-blob-1 absolute -top-24 left-1/4 h-[420px] w-[500px] rounded-full bg-[#FF7A5C]/25 blur-[120px]" />
        {/* Blob 2: Agent Violet */}
        <div className="aurora-blob-2 absolute bottom-0 right-1/4 h-[450px] w-[550px] rounded-full bg-[#5B47D6]/20 blur-[130px]" />
        {/* Blob 3: Calm Emerald / Jade */}
        <div className="aurora-blob-3 absolute top-1/3 right-1/3 h-[380px] w-[420px] rounded-full bg-[#0F7A5A]/20 blur-[110px]" />
        {/* Dark Vignette Overlay */}
        <div className="absolute inset-0 bg-radial-gradient from-transparent via-[#0D0B0A]/40 to-[#0D0B0A]/90" />
      </div>

      {/* 2. Content */}
      <div className="relative z-10 mx-auto max-w-3xl flex flex-col items-center">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/20 bg-white/10 px-4 py-1 backdrop-blur-md mb-6">
          <Sparkle size={13} className="text-[#FF7A5C]" />
          <span className="label-mono text-[11px] tracking-widest text-white/90">
            {landingCopy.finale.badge}
          </span>
        </div>

        <h2 className="landing-serif font-serif font-light text-[42px] sm:text-[64px] lg:text-[76px] leading-[1.08] tracking-[-0.02em] text-white">
          {landingCopy.finale.headline}
        </h2>

        <p className="mt-6 max-w-xl text-[16px] sm:text-[18px] text-white/80 leading-relaxed font-light">
          {landingCopy.finale.subhead}
        </p>

        <div className="mt-10 flex flex-col sm:flex-row items-center gap-4">
          <Link
            to="/"
            className="glass-pill-primary px-8 py-4 text-[16px] shadow-xl hover:shadow-coral/30"
          >
            Open FinCo
          </Link>

          <Link to="/design" className="glass-pill flex items-center gap-2 px-6 py-4 text-[14px]">
            <span>{landingCopy.finale.secondaryCta}</span>
            <ArrowRight size={14} />
          </Link>
        </div>

        <p className="mt-8 text-[12px] text-white/80">
          Pure web technology · No tracking cookies · Fully client-rendered
        </p>
      </div>
    </section>
  );
}
