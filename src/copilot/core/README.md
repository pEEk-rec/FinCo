# core (old paths)

Nothing lives here any more. Every file is a three-line pointer to the module's new home, kept so
that older imports, scripts and notes keep working:

| Old | New |
| --- | --- |
| `core.capture`, `core.capture_logic`, `core.sms_parser`, ... | `capture/` |
| `core.categorisation`, `core.pipeline` | `understand/` |
| `core.intent`, `core.answers`, `core.advice`, `core.investigation` | `conversation/` |
| `core.goals`, `core.forecast`, `core.simulation`, `core.buckets`, ... | `domain/` (`simulation` is now `whatif`) |
| `core.learning`, `core.learning_loop`, `core.policy`, `core.nudges` | `learning/` |
| `core.memory` | `memory/store` |
| `core.profile`, `core.budget_copilot`, `core.splits`, `core.subscriptions` | `personal/` |
| `core.checkin` | `agents/checkin` |
| `core.aa_*` | `banklink/` |
| `core.config`, `core.money`, `core.timeutil`, `core.errors` | `common/` |

Please import from the new home, and don't add code here.
