# agents

The parts of FinCo that act on their own initiative, and the list of every agent in the system.

## What's here

- **`registry.py`**: every agent in one table. For each one it records what wakes it (a question, a
  schedule, an event), what it's trying to achieve, how it runs, which tools it may use, how it
  checks itself, and where its result goes. `copilot agents` prints it. If you add an agent, add it
  here; a test fails if an entry points at code that doesn't exist.
- **`kernel.py`**: the shared loop for agents that decide by themselves when to act:

  ```
  precheck → perceive → rank → for each candidate: verify → propose → commit
  ```

  An agent fills in those steps; the kernel runs them in order, stops at the first candidate that
  survives every check, and returns an `AgentRun`. That holds each step taken, everything dropped
  (with the reason), and the outcome. "Nothing worth doing" is a normal outcome, not an error.
- **`checkin.py`**: the weekly check-in, the first agent on the kernel. It stays quiet in quiet hours
  and speaks at most twice a week. It looks for signals in your own money (a category running hot,
  a renewal coming, a goal drifting), puts your stated priorities first, recomputes each signal a
  second way before trusting it, and only says a sentence whose every number was computed.

## Why two kinds of loop

Answering a question is open-ended: it might need any of a hundred tools in any order, so it runs
as a LangGraph graph with a planner in the middle (see `workflow/`). A check-in is narrow and
repeated: one decision per run, the same steps each time. A fixed loop makes that easy to test and
easy to explain, which matters more than flexibility for something that interrupts you.

## Adding an agent

Subclass `Agent[YourCandidate]`, implement `perceive`, `verify`, `propose` and `commit` (and
`precheck`/`rank` if you need them), act only through `execute_tool` or audited writes, and add an
`AgentInfo` row to the registry. `tests/agents/` shows the contract with a toy agent.
