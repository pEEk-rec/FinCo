import { useReducedMotion } from 'motion/react';
import { useEffect, useMemo, useRef } from 'react';

import { categoryPalette, colors } from '../tokens/tokens';

/**
 * The constellation: a live picture of the categorisation pipeline (PLAN_UI 2.6).
 * Each particle is one real transaction; clusters are categories plus the review queue.
 * The component only draws what the spec says: it never invents assignments.
 */

export type ParticleState = 'unassigned' | 'rule' | 'ai' | 'review';

export interface ParticleSpec {
  id: string;
  state: ParticleState;
  /** Target cluster id, or null while unassigned. */
  clusterId: string | null;
}

export interface ClusterSpec {
  id: string;
  label: string;
  /** Index into the category palette (0-based); ignored for the review cluster. */
  hue: number;
  isReview?: boolean;
  /** Count shown beside the label, already formatted by the caller. */
  countText?: string;
}

export interface ConstellationProps {
  particles: ParticleSpec[];
  clusters: ClusterSpec[];
  height?: number;
  /** 'pipeline' shows cluster labels; 'ambient' is number-free drift for the welcome page. */
  mode?: 'pipeline' | 'ambient';
  ariaLabel: string;
  /** Frame-time probe for the performance test (ms of drawing work per frame). */
  onFrame?: (workMs: number) => void;
}

interface Body {
  x: number;
  y: number;
  vx: number;
  vy: number;
  angle: number;
  spin: number;
  size: number;
  seed: number;
  releaseAt: number;
}

const STATE_DELAY: Record<ParticleState, number> = {
  unassigned: 0,
  rule: 0,
  ai: 500,
  review: 1000,
};

/** Deterministic hash in [0, 1) for stable per-particle variation. */
function hash01(text: string, salt = 0): number {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return ((h >>> 0) % 100000) / 100000;
}

function hexToRgba(hex: string, alpha: number): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
}

/** Cluster centres laid out across the canvas; the review cluster sits apart on the right. */
function layoutClusters(clusters: ClusterSpec[], width: number, height: number) {
  const regular = clusters.filter((c) => !c.isReview);
  const review = clusters.find((c) => c.isReview);
  const cols = Math.max(1, Math.ceil(Math.sqrt(regular.length * 1.6)));
  const rows = Math.max(1, Math.ceil(regular.length / cols));
  const areaW = review ? width * 0.74 : width;
  const centres = new Map<string, { x: number; y: number; r: number }>();
  const r = Math.max(18, Math.min(areaW / cols, height / rows) * 0.3);
  regular.forEach((c, i) => {
    const col = i % cols;
    const row = Math.floor(i / cols);
    centres.set(c.id, {
      x: (areaW / cols) * (col + 0.5),
      y: (height / rows) * (row + 0.5) + (col % 2 ? r * 0.35 : -r * 0.35) * (rows > 1 ? 1 : 0),
      r,
    });
  });
  if (review)
    centres.set(review.id, { x: width * 0.87, y: height * 0.5, r: Math.max(26, r * 1.2) });
  return centres;
}

export function Constellation({
  particles,
  clusters,
  height = 360,
  mode = 'pipeline',
  ariaLabel,
  onFrame,
}: ConstellationProps) {
  const reduce = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const bodies = useRef(new Map<string, Body>());
  const specRef = useRef({ particles, clusters });
  useEffect(() => {
    specRef.current = { particles, clusters };
  });
  const sizeRef = useRef({ width: 0, height });
  const labelsRef = useRef<HTMLDivElement>(null);

  const clusterById = useMemo(() => new Map(clusters.map((c) => [c.id, c])), [clusters]);

  // Record when each particle's assignment arrives, staggered by state so rule matches settle
  // first, then AI, then review. Only changes reported by the data move a particle.
  useEffect(() => {
    const now = performance.now();
    const { width } = sizeRef.current;
    particles.forEach((p, i) => {
      let body = bodies.current.get(p.id);
      if (!body) {
        body = {
          x: hash01(p.id, 1) * Math.max(width, 1),
          y: hash01(p.id, 2) * height,
          vx: (hash01(p.id, 3) - 0.5) * 0.15,
          vy: (hash01(p.id, 4) - 0.5) * 0.15,
          angle: hash01(p.id, 5) * Math.PI * 2,
          spin: (hash01(p.id, 6) - 0.5) * 0.004,
          size: 3.5 + hash01(p.id, 7) * 2,
          seed: hash01(p.id, 8),
          releaseAt: Number.POSITIVE_INFINITY,
        };
        bodies.current.set(p.id, body);
      }
      if (p.clusterId && body.releaseAt === Number.POSITIVE_INFINITY) {
        body.releaseAt = now + STATE_DELAY[p.state] + (i % 60) * 12;
      }
    });
    const ids = new Set(particles.map((p) => p.id));
    for (const id of bodies.current.keys()) if (!ids.has(id)) bodies.current.delete(id);
  }, [particles, height]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let raf = 0;
    let visible = true;
    let last = performance.now();
    const dpr = Math.min(2, window.devicePixelRatio || 1);

    const resize = () => {
      const width = wrap.clientWidth || 600;
      sizeRef.current = { width, height };
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const placeLabels = (centres: ReturnType<typeof layoutClusters>) => {
      const host = labelsRef.current;
      if (!host) return;
      for (const node of Array.from(host.children) as HTMLElement[]) {
        const c = centres.get(node.dataset.cluster ?? '');
        if (!c) continue;
        node.style.transform = `translate(${c.x}px, ${c.y + c.r + 10}px) translateX(-50%)`;
      }
    };

    const frame = (time: number, settleInstantly: boolean) => {
      const start = performance.now();
      const dt = Math.min(48, time - last);
      last = time;
      const { width } = sizeRef.current;
      const { particles: specs, clusters: clusterSpecs } = specRef.current;
      const centres = layoutClusters(clusterSpecs, width, height);
      placeLabels(centres);
      ctx.clearRect(0, 0, width, height);

      for (const spec of specs) {
        const body = bodies.current.get(spec.id);
        if (!body) continue;
        const cluster = spec.clusterId ? centres.get(spec.clusterId) : undefined;
        const released = settleInstantly || time >= body.releaseAt;
        if (cluster && released) {
          // Target: a stable point inside the cluster; review items sit hollow at its edge.
          const theta = body.seed * Math.PI * 2;
          const radius =
            spec.state === 'review'
              ? cluster.r * (0.85 + body.seed * 0.25)
              : cluster.r * Math.sqrt(hash01(spec.id, 9)) * 0.8;
          const tx = cluster.x + Math.cos(theta) * radius;
          const ty = cluster.y + Math.sin(theta) * radius;
          if (settleInstantly) {
            body.x = tx;
            body.y = ty;
          } else {
            const k = 1 - Math.pow(0.0025, dt / 1000);
            body.x += (tx - body.x) * k;
            body.y += (ty - body.y) * k;
          }
        } else if (!settleInstantly) {
          body.x += body.vx * dt;
          body.y += body.vy * dt;
          if (body.x < 0 || body.x > width) body.vx *= -1;
          if (body.y < 0 || body.y > height) body.vy *= -1;
        }
        body.angle += body.spin * dt;

        const clusterSpec = spec.clusterId ? clusterById.get(spec.clusterId) : undefined;
        const assigned = Boolean(cluster && released);
        const hue =
          clusterSpec && !clusterSpec.isReview
            ? categoryPalette[clusterSpec.hue % categoryPalette.length]!
            : null;
        const stroke = !assigned
          ? hexToRgba(colors['ink-3'], mode === 'ambient' ? 0.35 : 0.55)
          : spec.state === 'review'
            ? colors['attention']
            : (hue?.mark ?? colors['ink-3']);

        ctx.save();
        ctx.translate(body.x, body.y);
        ctx.rotate(body.angle);
        ctx.beginPath();
        const s = body.size;
        ctx.moveTo(0, -s);
        ctx.lineTo(s * 0.87, s * 0.5);
        ctx.lineTo(-s * 0.87, s * 0.5);
        ctx.closePath();
        if (assigned && spec.state !== 'review' && hue) {
          ctx.fillStyle = hexToRgba(hue.mark, 0.22);
          ctx.fill();
        }
        ctx.lineWidth = 1.2;
        ctx.strokeStyle = stroke;
        ctx.stroke();
        ctx.restore();

        if (assigned && spec.state === 'ai') {
          ctx.beginPath();
          ctx.arc(body.x, body.y, s + 3, 0, Math.PI * 2);
          ctx.lineWidth = 1;
          ctx.strokeStyle = hexToRgba(colors.agent, 0.35);
          ctx.stroke();
        }
      }
      onFrame?.(performance.now() - start);
    };

    if (reduce) {
      frame(performance.now(), true);
      return;
    }

    const loop = (time: number) => {
      if (visible && document.visibilityState === 'visible') frame(time, false);
      else last = time;
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);

    const io =
      typeof IntersectionObserver !== 'undefined'
        ? new IntersectionObserver(([entry]) => {
            visible = Boolean(entry?.isIntersecting);
          })
        : null;
    io?.observe(canvas);
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null;
    ro?.observe(wrap);
    return () => {
      cancelAnimationFrame(raf);
      io?.disconnect();
      ro?.disconnect();
    };
  }, [height, reduce, mode, clusterById, onFrame]);

  return (
    <div ref={wrapRef} className="relative w-full overflow-hidden" style={{ height }}>
      <canvas ref={canvasRef} role="img" aria-label={ariaLabel} className="block" />
      {mode === 'pipeline' ? (
        <div ref={labelsRef} aria-hidden className="pointer-events-none absolute inset-0">
          {clusters.map((c) => (
            <span
              key={c.id}
              data-cluster={c.id}
              className={`absolute top-0 left-0 whitespace-nowrap text-small ${c.isReview ? 'text-attention' : 'text-ink-2'}`}
            >
              {c.label}
              {c.countText ? (
                <span className="tabular ml-1.5 text-ink-3">{c.countText}</span>
              ) : null}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}
