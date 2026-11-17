# workflow

The LangGraph graphs: how a question or a monthly run is carried out step by step.

## The graphs

- **The ask agent** (`agent_graph.py`, `agentic_nodes.py`, `agentic_state.py`):

  ```
  understand → (clarify?) → plan → validate → act → observe → (re-plan?) → finalize
  ```

  The planner (see `planner/`) proposes tool calls; each one runs through `execute_tool`; results
  are observed and the answer is composed from them. Every node appends to a trace, which the API
  returns and the UI shows.

- **The multi-agent supervisor** (`multi_agent_graph.py`, `decomposition.py`, `multi_agent.py`,
  `specialists.py`, `reviewer.py`), for questions that cross areas:

  ```
  decompose → specialists in parallel → merge → reviewer → (one revision at most) → answer
  ```

  Each specialist may only call its own tool subset; trying anything else is refused and recorded.
  If one specialist fails, the answer is partial and says what's missing rather than failing
  outright. The merge is deterministic. The reviewer is a Reflexion-style critic: it checks every
  sub-question was answered and every figure is grounded, and may send the answer back once.

- **The monthly run** (`graph.py`, `nodes.py`): ingest, categorise, analyse, draft advice, review,
  finalise. This is the original pipeline, still used for the monthly review.

## Rule

No node imports or calls a tool handler directly. Nodes call `execute_tool`, which keeps every step
inside policy and the audit log. `findings.py` turns tool outputs into typed findings, and `trace.py`
formats a run for the CLI.
