import { useEffect, useRef, useState } from 'react';

const SRC = '/videos/hero_background.mp4';
const POSTER = '/videos/hero_poster.jpg';
/** How long the end of one pass dissolves into the start of the next. */
const FADE_S = 1.4;

/**
 * The hero loop, made seamless. A plain `loop` jumps from the last frame to the first; here two
 * copies of the clip take turns, and the next one starts fading in just before the current one
 * ends. For visitors who prefer reduced motion, or if the video cannot play, the still frame stays.
 *
 * The clip sits as a soft, feathered window in the middle of the page: dim enough to read over,
 * clear enough to see. The top is cropped (the empty sky), never the bottom.
 */
export function HeroVideo() {
  const a = useRef<HTMLVideoElement>(null);
  const b = useRef<HTMLVideoElement>(null);
  const [front, setFront] = useState<0 | 1>(0);
  const [still, setStill] = useState(
    () => window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );

  useEffect(() => {
    if (still) return;
    const videos = [a.current, b.current];
    const current = videos[0];
    if (!current) return;
    void current.play().catch(() => setStill(true));
    let active = 0;
    let handing = false;
    const watch = () => {
      const v = videos[active];
      const next = videos[1 - active];
      if (!v || !next || !v.duration || handing) return;
      if (v.duration - v.currentTime <= FADE_S) {
        handing = true;
        next.currentTime = 0;
        void next.play().catch(() => undefined);
        active = 1 - active;
        setFront(active as 0 | 1);
        window.setTimeout(
          () => {
            videos[1 - active]?.pause();
            handing = false;
          },
          FADE_S * 1000 + 200,
        );
      }
    };
    const id = window.setInterval(watch, 120);
    return () => window.clearInterval(id);
  }, [still]);

  const base =
    'absolute inset-0 h-full w-full object-cover object-[46%_100%] transition-opacity ease-in-out';
  const fade = { transitionDuration: `${FADE_S * 1000}ms` };

  return (
    <div
      className="absolute inset-0 overflow-hidden [-webkit-mask-image:radial-gradient(ellipse_55%_62%_at_50%_60%,#000_30%,rgba(0,0,0,0.3)_100%)] [mask-image:radial-gradient(ellipse_55%_62%_at_50%_60%,#000_30%,rgba(0,0,0,0.3)_100%)]"
      aria-hidden="true"
    >
      <img
        src={POSTER}
        alt=""
        className="absolute inset-0 h-full w-full object-cover object-[46%_100%]"
      />
      {still ? null : (
        <>
          <video
            ref={a}
            muted
            playsInline
            preload="auto"
            poster={POSTER}
            className={base}
            style={{ ...fade, opacity: front === 0 ? 1 : 0 }}
            onError={() => setStill(true)}
          >
            <source src={SRC} type="video/mp4" />
          </video>
          <video
            ref={b}
            muted
            playsInline
            preload="auto"
            className={base}
            style={{ ...fade, opacity: front === 1 ? 1 : 0 }}
          >
            <source src={SRC} type="video/mp4" />
          </video>
        </>
      )}
    </div>
  );
}
