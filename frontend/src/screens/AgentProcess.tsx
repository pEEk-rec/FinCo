import type { ReactNode } from 'react';

import type { AskOut } from '../api/client';
import { Badge } from '../components/Badge';
import { cx } from '../components/cx';

interface IntentView {
  type?: string;
  period?: string | null;
  category_id?: string | null;
  confidence_label?: string;
  source?: string;
}

const label = (s: string) => s.replace(/_/g, ' ');

function Stage({
  name,
  title,
  note,
  children,
  tone = 'agent',
}: {
  name: string;
  title: string;
  note?: string;
  children?: ReactNode;
  tone?: 'agent' | 'negative' | 'attention';
}) {
  const dot =
    tone === 'negative' ? 'bg-negative' : tone === 'attention' ? 'bg-attention' : 'bg-agent';
  return (
    <li className="relative flex gap-4 pb-5 last:pb-0">
      <span
        aria-hidden
        className="absolute top-5 bottom-0 left-[5px] w-px bg-hairline-strong last:hidden"
      />
      <span aria-hidden className={cx('relative mt-1.5 size-[11px] shrink-0 rounded-full', dot)} />
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-3">
          <span className="label-mono text-agent">{name}</span>
          <span className="text-[14px] font-medium text-ink">{title}</span>
        </p>
        {note ? <p className="mt-0.5 text-small text-ink-2">{note}</p> : null}
        {children}
      </div>
    </li>
  );
}

/**
 * The agent's process for one request, drawn only from what the API reported: the intent it
 * understood, the plan it proposed (and that the validator accepted), the tools it ran through
 * the governed executor, and whether it paused for a human.
 */
export function AgentProcess({ result }: { result: AskOut }) {
  const intent = (result.intent ?? {}) as IntentView;
  const nodes = new Set(result.trace.map((t) => t.node));
  const durationOf = (node: string) =>
    result.trace.filter((t) => t.node === node).reduce((sum, t) => sum + t.duration_ms, 0);
  const planNode = result.trace.find((t) => t.node === 'plan');
  const rejections = planNode?.counts.rejections ?? 0;
  const reflect = result.trace.find((t) => t.node === 'reflect');
  const replanned = reflect?.counts.replanned ?? 0;
  const refused = Boolean(result.refusal_reason);

  return (
    <section aria-labelledby="process-title">
      <h3 id="process-title" className="label-mono mb-4 text-ink-2">
        How the agent worked
      </h3>
      <ol>
        <Stage
          name="Understand"
          title={
            refused ? 'Checked the request against its rules' : label(intent.type ?? 'unknown')
          }
          note={
            refused
              ? 'The input gate matches refusal classes before any model or tool is involved.'
              : [
                  intent.period ? `period ${intent.period}` : null,
                  intent.category_id ? `category ${intent.category_id}` : null,
                  `${intent.confidence_label ?? 'low'} confidence`,
                  `read by ${intent.source ?? 'rules'}`,
                ]
                  .filter(Boolean)
                  .join(' · ')
          }
        />
        {refused ? (
          <Stage
            name="Refuse"
            title="Stopped at the gate"
            tone="negative"
            note="No plan was made and no tool ran."
          />
        ) : null}
        {nodes.has('clarify') ? (
          <Stage
            name="Clarify"
            title="Asked one question instead of guessing"
            note="Entities are resolved against your own records; an unknown one is asked about, never invented."
          />
        ) : null}
        {result.plan.length > 0 ? (
          <Stage
            name="Plan"
            title={`${result.plan.length} step${result.plan.length === 1 ? '' : 's'}, proposed by ${result.planner_mode} planner`}
            note={
              rejections > 0
                ? 'The validator rejected a proposal and the safe baseline plan was used.'
                : 'Checked by the plan validator: allowed tools only, valid arguments, your own data only.'
            }
          >
            <ol className="mt-2 flex flex-col gap-1.5">
              {result.plan.map((step) => (
                <li key={step.seq} className="flex flex-wrap items-baseline gap-x-2 text-small">
                  <span className="tabular text-ink-3">{step.seq + 1}.</span>
                  <span className="font-medium capitalize text-ink">{label(step.tool_name)}</span>
                  <span className="text-ink-2">{step.rationale}</span>
                </li>
              ))}
            </ol>
          </Stage>
        ) : null}
        {result.observations.length > 0 ? (
          <Stage
            name="Act"
            title={`Ran ${result.observations.length} tool${result.observations.length === 1 ? '' : 's'} through the executor`}
            note={`Each call is policy-checked and audited. ${Math.round(durationOf('act'))} ms in total.`}
          >
            <ul className="mt-2 flex flex-wrap gap-2">
              {result.observations.map((o) => (
                <li key={`${o.step_seq}-${o.tool_name}`}>
                  <Badge tone={o.ok ? 'positive' : 'negative'}>{label(String(o.tool_name))}</Badge>
                </li>
              ))}
            </ul>
          </Stage>
        ) : null}
        {nodes.has('reflect') ? (
          <Stage
            name="Reflect"
            title={
              replanned > 0 ? 'Added a second round' : 'Checked whether the answer was good enough'
            }
            note={`Rounds used: ${result.rounds} of a hard limit of two.`}
          />
        ) : null}
        {nodes.has('synthesize') ? (
          <Stage
            name={result.pending_recommendations.length > 0 ? 'Review' : 'Finish'}
            title={
              result.pending_recommendations.length > 0
                ? 'Drafted a recommendation and waits for you'
                : 'Finished within its step budget'
            }
            tone={result.pending_recommendations.length > 0 ? 'attention' : 'agent'}
            note={
              result.pending_recommendations.length > 0
                ? 'Drafts never act on their own. They appear under Activity until you decide.'
                : result.stop_reason
                  ? `Stop reason: ${label(result.stop_reason)}`
                  : undefined
            }
          />
        ) : null}
      </ol>
    </section>
  );
}
