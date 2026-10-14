import { scaleLinear } from 'd3-scale';
import { area, curveMonotoneX, line } from 'd3-shape';
import { motion, useReducedMotion } from 'motion/react';
import { useState } from 'react';

import { formatINR } from '../format/money';
import { motion as tokens } from '../tokens/tokens';
import { firstDraw, useWidth } from './useSize';

export interface PacePoint {
  day: number;
  paise: number;
}

export interface PaceChartProps {
  chartId: string;
  daysInMonth: number;
  limitPaise: number | null;
  actual: PacePoint[];
  ideal: PacePoint[];
  forecastLow?: PacePoint[] | null;
  forecastHigh?: PacePoint[] | null;
  labels: { actual: string; ideal: string; limit: string; forecast?: string };
  /** Short label for the callout at the latest actual point (e.g. "₹420 under pace"). */
  callout?: { text: string; tone: 'positive' | 'negative' | 'neutral' } | null;
  height?: number;
}

const PAD = { top: 20, right: 64, bottom: 28, left: 8 };

/**
 * Month-to-date pace: actual cumulative spend, dashed ideal pace, budget limit and the
 * forecast band. Every coordinate comes from the API; this component only scales to pixels.
 */
export function PaceChart({
  chartId,
  daysInMonth,
  limitPaise,
  actual,
  ideal,
  forecastLow,
  forecastHigh,
  labels,
  callout,
  height = 220,
}: PaceChartProps) {
  const [ref, width] = useWidth<HTMLDivElement>(640);
  const reduce = useReducedMotion();
  const [animate] = useState(() => !reduce && firstDraw(chartId));

  const values = [
    ...actual.map((p) => p.paise),
    ...ideal.map((p) => p.paise),
    ...(forecastHigh ?? []).map((p) => p.paise),
    limitPaise ?? 0,
  ];
  const maxY = Math.max(1, ...values);
  const x = scaleLinear()
    .domain([1, Math.max(2, daysInMonth)])
    .range([PAD.left, width - PAD.right]);
  const y = scaleLinear()
    .domain([0, maxY * 1.08])
    .range([height - PAD.bottom, PAD.top]);

  const path = line<PacePoint>()
    .x((p) => x(p.day))
    .y((p) => y(p.paise))
    .curve(curveMonotoneX);

  const band =
    forecastLow &&
    forecastHigh &&
    forecastLow.length === forecastHigh.length &&
    forecastLow.length > 1
      ? area<number>()
          .x((i) => x(forecastLow[i]!.day))
          .y0((i) => y(forecastLow[i]!.paise))
          .y1((i) => y(forecastHigh[i]!.paise))
          .curve(curveMonotoneX)(forecastLow.map((_, i) => i))
      : null;

  const last = actual[actual.length - 1];
  const draw = (delay = 0) =>
    animate
      ? {
          initial: { pathLength: 0, opacity: 0 },
          animate: { pathLength: 1, opacity: 1 },
          transition: { duration: tokens.chart / 1000, ease: tokens.easeArray, delay },
        }
      : {};

  const ticks = [1, Math.ceil(daysInMonth / 2), daysInMonth];

  return (
    <div ref={ref} className="relative w-full">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={`${labels.actual}, ${labels.ideal}, ${labels.limit}`}
        className="block overflow-visible"
      >
        {band ? (
          <motion.path
            d={band}
            fill="var(--color-ink)"
            fillOpacity={0.07}
            initial={animate ? { opacity: 0 } : false}
            animate={{ opacity: 1 }}
            transition={{ duration: tokens.slow / 1000, delay: animate ? tokens.chart / 1000 : 0 }}
          />
        ) : null}
        {limitPaise != null ? (
          <g>
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={y(limitPaise)}
              y2={y(limitPaise)}
              stroke="var(--color-hairline-strong)"
              strokeWidth={1}
            />
            <text
              x={width - PAD.right + 8}
              y={y(limitPaise)}
              dominantBaseline="middle"
              className="fill-ink-3 font-mono text-[10px] tracking-[0.06em] uppercase"
            >
              {labels.limit}
            </text>
            <text
              x={width - PAD.right + 8}
              y={y(limitPaise) + 13}
              dominantBaseline="middle"
              className="tabular fill-ink-2 text-[11px]"
            >
              {formatINR(limitPaise, { compact: true })}
            </text>
          </g>
        ) : null}
        {ideal.length > 1 ? (
          <motion.path
            d={path(ideal) ?? undefined}
            fill="none"
            stroke="var(--color-ink-3)"
            strokeWidth={1}
            strokeDasharray="3 4"
            {...draw()}
          />
        ) : null}
        {actual.length > 1 ? (
          <motion.path
            d={path(actual) ?? undefined}
            fill="none"
            stroke="var(--color-ink)"
            strokeWidth={2}
            strokeLinecap="round"
            {...draw(0.1)}
          />
        ) : null}
        {last ? (
          <motion.circle
            cx={x(last.day)}
            cy={y(last.paise)}
            r={4}
            fill="var(--color-surface)"
            stroke="var(--color-ink)"
            strokeWidth={2}
            initial={animate ? { opacity: 0 } : false}
            animate={{ opacity: 1, cx: x(last.day), cy: y(last.paise) }}
            transition={{ duration: tokens.slow / 1000, ease: tokens.easeArray }}
          />
        ) : null}
        {ticks.map((day) => (
          <text
            key={day}
            x={x(day)}
            y={height - 6}
            textAnchor={day === 1 ? 'start' : day === daysInMonth ? 'end' : 'middle'}
            className="tabular fill-ink-3 text-[11px]"
          >
            {day}
          </text>
        ))}
      </svg>
      {last && callout ? (
        <motion.span
          className={`label-mono absolute rounded-[4px] px-1.5 py-0.5 whitespace-nowrap ${
            callout.tone === 'positive'
              ? 'bg-positive-tint text-positive'
              : callout.tone === 'negative'
                ? 'bg-negative-tint text-negative'
                : 'bg-surface-sunken text-ink-2'
          }`}
          style={{ left: x(last.day), top: y(last.paise) - 30, translateX: '-50%' }}
          initial={animate ? { opacity: 0, y: 4 } : false}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: tokens.base / 1000, delay: animate ? tokens.chart / 1000 : 0 }}
        >
          {callout.text}
        </motion.span>
      ) : null}
    </div>
  );
}
