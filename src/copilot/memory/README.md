# memory

What FinCo remembers about you, why, and how sure it is.

There are two kinds of memory. The **run's own state** lives in the graph for the length of a
question and is gone after. The **long-term store** (`store.py`) holds behaviours FinCo has seen
in your data: "food spend goes up in festival months", "you usually top up savings on payday".

Each long-term memory has:

- **evidence**: the transactions or events it came from, so you can see why it exists;
- **confidence** that fades over time unless new evidence keeps it fresh, with the decay
  computed deterministically;
- **a status** you control. You can confirm it, reject it, edit what it says, or forget it.
  Forgetting is real deletion, not a hidden flag.

Observers propose memories from data, and no model writes to memory. Retrieval for a prompt is
ranked by how well a memory matches the subject, how confident it is, and how recent it is
(`context/retrieval.py`).

**`exception_windows.py`** reads declared exceptions (a festival month, a trip) as date ranges, so
alerts and challenges don't nag you about spending you already explained.
