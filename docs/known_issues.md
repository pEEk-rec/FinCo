# Known Issues (Phase 3)

This file tracks minor, non-blocking items (naming, doc typos, future enhancements) noticed during development to be resolved in future iterations, without distracting from mid-stage execution.

| Area | Component | Description | Status |
|---|---|---|---|
| LangGraph Checkpoint | `agent_graph.py` | In-memory `MemorySaver` used for testing; production deployments should attach persistent SQLite checkpointer (`SqliteSaver`). | Documented / Tracked |
| Real-time AA Webhook | `api/app.py` | Account Aggregator statement ingest currently triggers via batch poll or CLI; webhook endpoint ready for forward integration. | Deferred to Future Scope |
| MCP SSE Transport | `mcp/server.py` | MCP currently supports stdio and in-process execution; Server-Sent Events (SSE) transport can be added when remote network MCP is required. | Deferred to Future Scope |

---
*All 943 automated regression tests passing. Zero critical bugs or security blockers.*

# Known Issues (Phase 4)

| Area | Component | Description | Status |
|---|---|---|---|
| Measurement | `core/baseline.py` | With K=6 earlier periods a quiet period is called "beyond your usual range" about 1 time in 7 by chance; real cuts of about 35% are detected about half the time (eval report section 1). The wording never says "significant". More history (K=12) lowers the chance rate but needs about a year of data. | Known limit |
| Intent reading | `core/intent.py` | Held-out accuracy of the rule-based reader is 75% (target 80%); a configured model reads first and helps on paraphrases, but the model path is checked on only 25 recorded questions per set. | Open |
| CLI | `copilot ask` | The terminal answer for `what_worked` and `progress_summary` is the generic line "Analyzed what_worked ..."; the evidence is in the tool observations, the API and `copilot progress` / `experiments review`. | Open |
| CLI | `copilot progress` | No `--clock` option, so streaks on old data are measured to today and look very long. | Open |
| CLI | `copilot experiments show` | The hypothesis line prints "Intervention: None / Target: None" for offer-created experiments. | Cosmetic |
| Demo | `scripts/demo_phase4.sh` | Needs one direct database edit (a lower food budget) because no CLI command sets a budget. | Documented |
| Exceptions | `memory exception` | A range can be at most 93 days and covers one category per command. | By design |
