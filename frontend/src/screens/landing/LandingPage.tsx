import { useEffect } from 'react';

import { captureTokenFromHash } from '../../api/client';
import { HeroSection } from './HeroSection';

/** The landing page is the hero alone: a figure above the clouds and a few plain words. */
export function LandingPage() {
  // Capture any session token in URL hash on arrival
  useEffect(() => {
    captureTokenFromHash();
  }, []);

  return (
    <div className="min-h-svh w-full bg-[#0D0B0A] font-sans antialiased text-white selection:bg-coral/30">
      <HeroSection />
    </div>
  );
}
