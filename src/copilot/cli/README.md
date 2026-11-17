# cli

The `copilot` command. Everything the web app can do, plus the operator tools (evaluation, jobs,
traces, the MCP server).

`app.py` defines the root command and its groups; each area's commands live in their own module
(`ledger.py`, `goals.py`, `ask.py`, `capture.py`, `personal.py`, `runtime.py`, ...), and
`main.py` imports them so they're registered. The import order there is the order `--help` lists
them in. Commands call tools through `execute_tool`, just like the API.

A few to start with:

```bash
copilot init-db && copilot seed          # a demo database with three months of data
copilot ask "why did food go up in February"
copilot understand run                   # categorise what isn't answered yet
copilot me budget                        # the budget co-pilot
copilot agents                           # every agent and how it runs
copilot eval --list                      # the evaluation suites
copilot trace --run <id>                 # what happened in one run, step by step
```
