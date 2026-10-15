# Known Issues (Phase 3)

This file tracks minor, non-blocking items (naming, doc typos, future enhancements) noticed during development to be resolved in future iterations, without distracting from mid-stage execution.

| Area | Component | Description | Status |
|---|---|---|---|
| LangGraph Checkpoint | `agent_graph.py` | In-memory `MemorySaver` used for testing; production deployments should attach persistent SQLite checkpointer (`SqliteSaver`). | Documented / Tracked |
| Real-time AA Webhook | `api/app.py` | Account Aggregator statement ingest currently triggers via batch poll or CLI; webhook endpoint ready for forward integration. | Deferred to Future Scope |
| MCP SSE Transport | `mcp/server.py` | MCP currently supports stdio and in-process execution; Server-Sent Events (SSE) transport can be added when remote network MCP is required. | Deferred to Future Scope |

---
*All 943 automated regression tests passing. Zero critical bugs or security blockers.*
