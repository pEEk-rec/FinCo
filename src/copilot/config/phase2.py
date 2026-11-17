"""Old phase-named module, kept so earlier imports still work. See the modules imported below."""

from copilot.config.loading import (  # noqa: F401
    load_yaml,
)
from copilot.config.money import (  # noqa: F401
    AlertsConfig,
    GoalsConfig,
    WhatIfConfig,
    load_alerts_config,
    load_goals_config,
    load_whatif_config,
)
from copilot.config.planning import (  # noqa: F401
    CONFIG_DIR,
    ExplanationTemplatesConfig,
    IntentPatternsConfig,
    InvestigationConfig,
    PlannerCapabilitiesConfig,
    PlanTemplate,
    PlanTemplatesConfig,
    StepTemplate,
    ToolCapability,
    load_explanation_templates,
    load_intent_patterns,
    load_investigation_config,
    load_plan_templates,
    load_planner_capabilities,
)
