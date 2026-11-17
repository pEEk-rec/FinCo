# planner

Turning a question into the smallest list of tool calls that answers it, and refusing any plan
that oversteps.

- **`deterministic.py`** maps each kind of question to a known minimal plan
  (`config/plan_templates.yaml`). This is the default, and it's what runs when there's no model.
- **`llm_planner.py`** lets a model propose a plan, from the planner-selectable tools only, as
  structured output. It's tried for questions the templates don't cover.
- **`validator.py`** checks every plan, whoever wrote it. Every tool must exist and be
  planner-selectable, the arguments must validate, the plan must stay within its step budget, and a
  read-only question may not contain a write. A rejected plan is audited and replaced by the
  deterministic one. A bad model plan never runs.
- **`capabilities.py`** loads `config/planner_capabilities.yaml`, which says which tools a planner
  may see at all. Only `read` and `compute` tools can be chosen freely; writes need a human.
- **`execution.py`** runs the validated steps through `execute_tool`.
- **`router.py`** is the minimal planner interface.
