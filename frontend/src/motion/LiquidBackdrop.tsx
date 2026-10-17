import { useEffect, useRef } from 'react';

/**
 * The room's light: a few soft blobs of coral, peach, lilac and mint drifting slowly behind everything,
 * leaning gently towards the pointer. Drawn at a fraction of the screen size and blurred by CSS,
 * so it costs almost nothing. Pauses when the tab is hidden and draws one still frame when the
 * visitor prefers reduced motion. Purely atmospheric: it carries no data.
 */
interface Blob {
  hue: string;
  r: number;
  ax: number;
  ay: number;
  sx: number;
  sy: number;
  px: number;
  py: number;
  pull: number;
}

const BLOBS: Blob[] = [
  {
    hue: '255, 122, 92',
    r: 0.42,
    ax: 0.32,
    ay: 0.22,
    sx: 0.00021,
    sy: 0.00017,
    px: 0,
    py: 1,
    pull: 0.06,
  },
  {
    hue: '255, 182, 140',
    r: 0.46,
    ax: 0.28,
    ay: 0.3,
    sx: 0.00015,
    sy: 0.00023,
    px: 2,
    py: 3,
    pull: 0.1,
  },
  {
    hue: '176, 160, 255',
    r: 0.28,
    ax: 0.38,
    ay: 0.2,
    sx: 0.00026,
    sy: 0.00014,
    px: 4,
    py: 5,
    pull: 0.14,
  },
  {
    hue: '122, 208, 190',
    r: 0.4,
    ax: 0.22,
    ay: 0.34,
    sx: 0.00012,
    sy: 0.00019,
    px: 6,
    py: 1,
    pull: 0.04,
  },
];

export function LiquidBackdrop() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const SCALE = 0.16; // draw at 16% size; CSS scales and blurs it
    const pointer = { x: 0.5, y: 0.4, tx: 0.5, ty: 0.4 };
    let w = 0;
    let h = 0;
    let raf = 0;
    let last = 0;

    const resize = () => {
      w = Math.max(80, Math.round(window.innerWidth * SCALE));
      h = Math.max(60, Math.round(window.innerHeight * SCALE));
      canvas.width = w;
      canvas.height = h;
    };

    const draw = (t: number) => {
      pointer.x += (pointer.tx - pointer.x) * 0.04;
      pointer.y += (pointer.ty - pointer.y) * 0.04;
      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = 'source-over';
      for (const b of BLOBS) {
        const cx = (0.5 + b.ax * Math.sin(t * b.sx + b.px) + (pointer.x - 0.5) * b.pull) * w;
        const cy = (0.5 + b.ay * Math.cos(t * b.sy + b.py) + (pointer.y - 0.5) * b.pull) * h;
        const rad = b.r * Math.max(w, h);
        const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, rad);
        g.addColorStop(0, `rgba(${b.hue}, 0.42)`);
        g.addColorStop(0.55, `rgba(${b.hue}, 0.14)`);
        g.addColorStop(1, `rgba(${b.hue}, 0)`);
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, w, h);
      }
    };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (now - last < 33) return; // about 30 frames a second is plenty for something this soft
      last = now;
      draw(now);
    };

    const onMove = (e: PointerEvent) => {
      pointer.tx = e.clientX / window.innerWidth;
      pointer.ty = e.clientY / window.innerHeight;
    };
    const onVisibility = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden && !reduce) raf = requestAnimationFrame(frame);
    };

    resize();
    draw(0);
    window.addEventListener('resize', resize);
    if (!reduce) {
      window.addEventListener('pointermove', onMove, { passive: true });
      document.addEventListener('visibilitychange', onVisibility);
      raf = requestAnimationFrame(frame);
    }
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onMove);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  return (
    <canvas
      ref={ref}
      aria-hidden
      className="no-print pointer-events-none fixed inset-0 -z-10 h-full w-full opacity-80"
      style={{ filter: 'blur(36px) saturate(1.15)' }}
    />
  );
}
