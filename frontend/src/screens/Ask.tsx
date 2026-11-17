import {
  ArrowUp,
  CaretDown,
  Check,
  ClockCounterClockwise,
  ShieldCheck,
  Sparkle,
  X,
} from '@phosphor-icons/react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { streamAsk, type AgentStep } from '../api/askStream';
import { ApiError, type AskOut } from '../api/client';
import { useCategories, useSession } from '../api/hooks';
import { Badge } from '../components/Badge';
import { Button } from '../components/Button';
import { cx } from '../components/cx';
import { ErrorState } from '../components/States';
import { copy } from '../copy/en';
import { ActivityPanel, ObservationData } from './Agent';

const T = copy.ask;

interface Fact {
  label: string;
  text: string;
}

interface Turn {
  id: number;
  text: string;
  pending: boolean;
  /** What the agent has done so far, in order, as it streams in. */
  steps: AgentStep[];
  result?: AskOut;
  error?: ApiError | Error;
}

const spring = { type: 'spring', stiffness: 380, damping: 32 } as const;

function factsOf(result: AskOut | undefined): Fact[] {
  const raw = result?.answer?.facts ?? [];
  return raw.filter(
    (f): f is Fact =>
      typeof f === 'object' &&
      f !== null &&
      typeof (f as Fact).text === 'string' &&
      typeof (f as Fact).label === 'string',
  );
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * The answer text with every computed figure marked. A figure is only ever one of the facts the
 * backend computed (the answer is rejected otherwise), so hovering one says what it is.
 */
function Grounded({ text, facts }: { text: string; facts: Fact[] }) {
  const parts = useMemo(() => {
    const usable = facts.filter((f) => f.text.trim() !== '');
    if (usable.length === 0) return [text];
    const byText = new Map(usable.map((f) => [f.text, f]));
    const pattern = new RegExp(
      `(${[...byText.keys()]
        .sort((a, b) => b.length - a.length)
        .map(escape)
        .join('|')})`,
      'g',
    );
    return text.split(pattern).map((piece, i) => {
      const fact = byText.get(piece);
      return fact ? (
        <mark
          key={i}
          title={fact.label}
          className="tabular rounded-[6px] bg-positive-tint px-1 py-px font-semibold text-positive"
        >
          {piece}
        </mark>
      ) : (
        piece
      );
    });
  }, [text, facts]);
  return <>{parts}</>;
}

function seconds(ms: number): string {
  return `${(ms / 1000).toFixed(1)}s`;
}

function summaryOf(result: AskOut, facts: number): string {
  if (result.refusal_reason) return 'Stopped at the gate · no plan made, no tool ran';
  if (result.question) return 'Needs one detail before it can answer';
  const steps = result.plan.length;
  const tools = new Set(result.observations.map((o) => String(o.tool_name))).size;
  const bits = [`${steps} step${steps === 1 ? '' : 's'}`, `${tools} tool${tools === 1 ? '' : 's'}`];
  if (facts > 0) bits.push(`${facts} figure${facts === 1 ? '' : 's'} checked`);
  return `Worked it out · ${bits.join(' · ')}`;
}

/** One thing the agent did: a dot that pulses while it is the latest, its words, and what it found. */
function StepRow({
  step,
  working,
  names,
}: {
  step: AgentStep;
  working: boolean;
  names: Map<string, string>;
}) {
  const reduce = useReducedMotion();
  const bad = step.tone === 'stop' || step.ok === false;
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={spring}
      className="relative flex gap-3 pb-4 last:pb-0"
      data-stage={step.stage}
    >
      <span
        aria-hidden
        className={cx(
          'mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-ink-inverse',
          bad ? 'bg-negative' : 'bg-agent',
          working && !reduce && 'animate-pulse',
        )}
      >
        {working ? (
          <span className="size-1.5 rounded-full bg-ink-inverse" />
        ) : bad ? (
          <X size={11} weight="bold" />
        ) : (
          <Check size={11} weight="bold" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-2.5">
          <span className="text-[14px] font-semibold text-ink">{step.title}</span>
          <span className="tabular text-small text-ink-3">{seconds(step.ms)}</span>
        </p>
        {step.detail ? <p className="mt-0.5 text-small text-ink-2">{step.detail}</p> : null}
        {step.stage === 'plan' && step.steps?.length ? (
          <ol className="mt-1.5 flex flex-col gap-1">
            {step.steps.map((s) => (
              <li key={s.seq} className="flex flex-wrap items-baseline gap-x-2 text-small">
                <span className="tabular text-ink-3">{s.seq + 1}.</span>
                <span className="font-mono text-[12.5px] text-ink">{s.tool_name}</span>
                <span className="text-ink-2">{s.rationale}</span>
              </li>
            ))}
          </ol>
        ) : null}
        {step.stage === 'act' && step.data ? (
          <ObservationData names={names} name={String(step.tool)} data={step.data} />
        ) : null}
      </div>
    </motion.li>
  );
}

/** Like the "thinking" row in chat apps: open while the agent works, one line when it is done. */
function Reasoning({ turn, names }: { turn: Turn; names: Map<string, string> }) {
  const [chosen, setChosen] = useState<boolean | null>(null);
  const reduce = useReducedMotion();
  const open = chosen ?? turn.pending;
  const result = turn.result;
  const facts = factsOf(result).length;
  const latest = turn.steps[turn.steps.length - 1];
  const label = turn.pending
    ? (latest?.title ?? T.working)
    : result
      ? summaryOf(result, facts)
      : 'Could not finish';
  return (
    <div data-testid="ask-process" data-open={open ? 'true' : 'false'}>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setChosen(!open)}
        className="group flex items-center gap-2 rounded-full py-1 pr-2 text-left text-[13.5px] font-medium text-ink-3 transition-colors duration-fast hover:text-ink"
      >
        <span
          aria-hidden
          className={cx(
            'flex size-6 items-center justify-center rounded-full bg-agent-tint text-agent',
            turn.pending && !reduce && 'animate-pulse',
          )}
        >
          <Sparkle size={13} weight="fill" />
        </span>
        <span className={turn.pending ? 'shimmer-text' : ''}>{label}</span>
        {latest ? <span className="tabular text-ink-3">· {seconds(latest.ms)}</span> : null}
        <CaretDown
          size={13}
          weight="bold"
          aria-hidden
          className={cx('transition-transform duration-fast', open && 'rotate-180')}
        />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            initial={reduce ? false : { height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={reduce ? undefined : { height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.2, 0.8, 0.2, 1] }}
            className="overflow-hidden"
          >
            <div className="mt-2 ml-3 border-l-2 border-agent/25 py-2 pl-5">
              <h3 className="label-mono mb-3 text-ink-2">How the agent worked</h3>
              {turn.steps.length === 0 ? (
                <p className="text-small text-ink-2">Starting…</p>
              ) : (
                <ol aria-live="polite">
                  {turn.steps.map((step, i) => (
                    <StepRow
                      key={`${i}-${step.stage}`}
                      step={step}
                      names={names}
                      working={turn.pending && i === turn.steps.length - 1}
                    />
                  ))}
                </ol>
              )}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

function Answer({ result, onAsk }: { result: AskOut; onAsk: (text: string) => void }) {
  const answer = result.answer;
  const facts = factsOf(result);
  const hasFacts = facts.length > 0;
  if (!answer) return null;
  return (
    <div className="flex flex-col gap-4" data-testid="ask-answer">
      <p className="serif-light text-[23px] leading-snug text-ink">
        <Grounded text={answer.headline} facts={facts} />
      </p>
      {answer.points.length > 0 ? (
        <ul className="flex flex-col gap-2 text-[15.5px] leading-relaxed text-ink-2">
          {answer.points.map((point) => (
            <li key={point} className="flex gap-3">
              <span aria-hidden className="mt-[0.65em] size-1.5 shrink-0 rounded-full bg-ink-3" />
              <span>
                <Grounded text={point} facts={facts} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {facts.length > 0 ? (
        <details className="group rounded-control border border-hairline bg-surface-sunken/40">
          <summary className="flex cursor-pointer select-none items-center gap-2 px-4 py-2.5 text-small font-medium text-ink-2 hover:text-ink">
            <ShieldCheck size={16} weight="fill" aria-hidden className="text-positive" />
            {T.numbersUsed}
            <span className="tabular text-ink-3">({facts.length})</span>
            <CaretDown
              size={12}
              weight="bold"
              aria-hidden
              className="ml-auto transition-transform group-open:rotate-180"
            />
          </summary>
          <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-1.5 border-t border-hairline px-4 py-3 text-small">
            {facts.map((f) => (
              <div key={f.text} className="contents">
                <dt className="text-ink-2">{f.label}</dt>
                <dd className="tabular text-right font-semibold text-ink">{f.text}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
      <p className="flex flex-wrap items-center gap-2 text-small text-ink-3">
        <Badge tone={answer.written_by === 'ai' ? 'agent' : 'neutral'}>
          {answer.written_by === 'ai' ? T.byAi : T.byRules}
        </Badge>
        {answer.confidence ? <span>Confidence: {answer.confidence}</span> : null}
        {hasFacts ? <span>· {T.grounded}</span> : null}
      </p>
      {answer.followups.length > 0 ? (
        <ul className="flex flex-wrap gap-2">
          {answer.followups.map((q) => (
            <li key={q}>
              <button
                type="button"
                onClick={() => onAsk(q)}
                className="rounded-full border border-agent/25 bg-surface px-3.5 py-1.5 text-left text-small font-medium text-agent transition-[background-color,transform] duration-fast hover:bg-agent-tint active:scale-[0.97]"
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Clarify({ question, onAnswer }: { question: string; onAnswer: (text: string) => void }) {
  const [value, setValue] = useState('');
  return (
    <form
      className="flex flex-col gap-3 rounded-card bg-agent-tint p-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onAnswer(value.trim());
      }}
    >
      <p className="label-mono text-agent">{copy.agent.clarify}</p>
      <p className="text-[15px] text-ink">{question}</p>
      <div className="flex gap-2">
        <input
          className="h-10 w-full rounded-control border border-input-border bg-surface px-3 text-[14px]"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-label={copy.agent.clarify}
        />
        <Button type="submit" variant="primary">
          {copy.common.confirm}
        </Button>
      </div>
    </form>
  );
}

function TurnView({
  turn,
  names,
  onAsk,
  onClarify,
}: {
  turn: Turn;
  names: Map<string, string>;
  onAsk: (text: string) => void;
  onClarify: (turn: Turn, answer: string) => void;
}) {
  const reduce = useReducedMotion();
  const result = turn.result;
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={spring}
      className="flex flex-col gap-4"
    >
      <p className="ml-auto max-w-[85%] rounded-[20px] rounded-br-md bg-ink px-4 py-2.5 text-[15px] leading-snug text-ink-inverse">
        {turn.text}
      </p>
      <div className="flex flex-col gap-3">
        <Reasoning turn={turn} names={names} />
        {turn.error ? (
          <ErrorState
            code={turn.error instanceof ApiError ? turn.error.code : 'UNKNOWN'}
            message={turn.error.message}
            onRetry={() => onAsk(turn.text)}
          />
        ) : null}
        {result?.refusal_reason ? (
          <div className="rounded-card bg-negative-tint p-4">
            <p className="font-semibold text-negative">{copy.agent.refused}</p>
            <p className="mt-1 text-[15px] text-ink">{result.refusal_reason}</p>
            <p className="mt-2 text-small text-ink-2">{T.canInstead}</p>
          </div>
        ) : result?.question ? (
          <Clarify question={result.question} onAnswer={(a) => onClarify(turn, a)} />
        ) : result ? (
          <Answer result={result} onAsk={onAsk} />
        ) : null}
      </div>
    </motion.li>
  );
}

function ActivitySheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const reduce = useReducedMotion();
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  return (
    <AnimatePresence>
      {open ? (
        <>
          <motion.button
            type="button"
            aria-label={copy.common.close}
            onClick={onClose}
            className="fixed inset-0 z-40 bg-ink/25"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          />
          <motion.aside
            aria-label={T.activity}
            initial={reduce ? false : { x: '100%' }}
            animate={{ x: 0 }}
            exit={reduce ? undefined : { x: '100%' }}
            transition={{ type: 'spring', stiffness: 360, damping: 38 }}
            className="fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col overflow-y-auto border-l border-hairline bg-canvas shadow-[-30px_0_60px_-30px_rgba(31,26,23,0.35)]"
          >
            <div className="sticky top-0 z-10 flex items-center justify-between border-b border-hairline bg-canvas/90 px-6 py-4 backdrop-blur">
              <div>
                <h2 className="text-[18px] font-semibold">{T.activity}</h2>
                <p className="text-small text-ink-3">{T.activityLead}</p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label={copy.common.close}
                className="flex size-9 items-center justify-center rounded-full hover:bg-surface-sunken"
              >
                <X size={18} aria-hidden />
              </button>
            </div>
            <div className="p-6">
              <ActivityPanel />
            </div>
          </motion.aside>
        </>
      ) : null}
    </AnimatePresence>
  );
}

function Shell({ children, onActivity }: { children: ReactNode; onActivity: () => void }) {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-4rem)] w-full max-w-3xl flex-col px-5 pt-8 sm:px-8">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="serif-light text-[34px] tracking-[-0.01em] sm:text-[40px]">{T.title}</h1>
          <p className="mt-1 max-w-xl text-small text-ink-2">{T.lead}</p>
        </div>
        <Button variant="text" icon={<ClockCounterClockwise size={16} />} onClick={onActivity}>
          {T.activity}
        </Button>
      </div>
      {children}
    </div>
  );
}

/** Ask: one conversation, where every answer shows how it was worked out and what it rests on. */
export function AskScreen() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState('');
  const [activity, setActivity] = useState(false);
  const session = useSession();
  const [useLlm, setUseLlm] = useState(true);
  const categories = useCategories();
  const names = useMemo(
    () => new Map((categories.data ?? []).map((c) => [c.id, c.name])),
    [categories.data],
  );
  const nextId = useRef(1);
  const end = useRef<HTMLDivElement>(null);
  const busy = turns.some((t) => t.pending);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [turns]);

  const controllers = useRef(new Set<AbortController>());
  useEffect(() => {
    const running = controllers.current;
    return () => running.forEach((c) => c.abort());
  }, []);

  const patch = (id: number, change: (t: Turn) => Turn) =>
    setTurns((all) => all.map((t) => (t.id === id ? change(t) : t)));

  const run = (id: number, question: string, clarification?: string) => {
    const controller = new AbortController();
    controllers.current.add(controller);
    streamAsk({
      text: question,
      clarification,
      useLlm,
      signal: controller.signal,
      onStep: (step) => patch(id, (t) => ({ ...t, steps: [...t.steps, step] })),
    })
      .then((result) => patch(id, (t) => ({ ...t, pending: false, result })))
      .catch((error: Error) => {
        if (error.name === 'AbortError') return;
        patch(id, (t) => ({ ...t, pending: false, error }));
      })
      .finally(() => controllers.current.delete(controller));
  };

  const ask = (question: string) => {
    const q = question.trim();
    if (!q || busy) return;
    const id = nextId.current++;
    setTurns((all) => [...all, { id, text: q, pending: true, steps: [] }]);
    setText('');
    run(id, q);
  };

  const clarify = (turn: Turn, answer: string) => {
    setTurns((all) =>
      all.map((t) =>
        t.id === turn.id
          ? { ...t, pending: true, steps: [], result: undefined, error: undefined }
          : t,
      ),
    );
    run(turn.id, turn.text, answer);
  };

  return (
    <Shell onActivity={() => setActivity(true)}>
      {turns.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-6 pb-10 text-center">
          <span className="flex size-14 items-center justify-center rounded-[18px] bg-agent-tint text-agent shadow-[0_12px_30px_-14px_rgba(91,71,214,0.55)]">
            <Sparkle size={26} weight="fill" aria-hidden />
          </span>
          <p className="serif-light text-[28px]">{T.empty}</p>
          <ul className="grid w-full max-w-2xl gap-2.5 sm:grid-cols-2">
            {copy.agent.examples.map((example) => (
              <li key={example}>
                <button
                  type="button"
                  onClick={() => ask(example)}
                  className="h-full w-full rounded-card border border-hairline bg-surface px-4 py-3 text-left text-[14.5px] text-ink-2 transition-[border-color,transform,box-shadow] duration-fast hover:-translate-y-0.5 hover:border-agent/30 hover:text-ink hover:shadow-[0_10px_28px_-16px_rgba(91,71,214,0.45)]"
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <ol className="flex flex-1 flex-col gap-10 pb-8">
          {turns.map((t) => (
            <TurnView key={t.id} turn={t} names={names} onAsk={ask} onClarify={clarify} />
          ))}
        </ol>
      )}
      <div ref={end} />

      <div className="sticky bottom-20 z-20 -mx-2 pb-4 lg:bottom-0">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(text);
          }}
          className="flex items-center gap-2 rounded-[22px] border border-hairline bg-surface/95 p-2 pl-5 shadow-[0_18px_50px_-24px_rgba(31,26,23,0.35)] backdrop-blur-xl focus-within:border-agent/40"
        >
          <label className="flex-1">
            <span className="sr-only">{T.send}</span>
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={T.placeholder}
              maxLength={500}
              aria-label={T.send}
              className="h-10 w-full bg-transparent text-[15px] text-ink outline-none placeholder:text-ink-3"
            />
          </label>
          <button
            type="submit"
            aria-label={T.send}
            disabled={!text.trim() || busy}
            className="flex size-10 items-center justify-center rounded-full bg-agent text-ink-inverse transition-[transform,opacity] duration-fast hover:scale-105 active:scale-95 disabled:opacity-35 disabled:hover:scale-100"
          >
            <ArrowUp size={18} weight="bold" aria-hidden />
          </button>
        </form>
        {session.data?.llm_available ? (
          <label className="mt-2 flex items-center justify-center gap-2 text-small text-ink-3">
            <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
            Let AI plan and word the answer (the numbers always come from your data)
          </label>
        ) : null}
      </div>

      <ActivitySheet open={activity} onClose={() => setActivity(false)} />
    </Shell>
  );
}
