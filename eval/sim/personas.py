"""
Decision-level simulation personas with latent preferences and drift.
(PLAN_PHASE4 Section 6 & Stage 4.9)
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEV_SEEDS = [42, 101, 2024]
HELD_OUT_SEEDS = [999, 12345, 88888]


@dataclass
class ArmPreference:
    p_accept: float
    p_complete: float
    p_helpful: float

    @property
    def expected_reward(self) -> float:
        """Expected reward per offer: P(accept) * P(complete|accept) * P(helpful|complete)"""
        return self.p_accept * self.p_complete * self.p_helpful


@dataclass
class Persona:
    name: str
    description: str
    preferences: dict[str, ArmPreference]
    drift_after_week: int = 26
    drifted_preferences: dict[str, ArmPreference] = field(default_factory=dict)

    def get_preference(self, template_code: str, week: int = 1) -> ArmPreference:
        """Return latent preferences, applying drift if week > drift_after_week."""
        prefs = self.preferences
        if self.drift_after_week and week > self.drift_after_week and self.drifted_preferences:
            prefs = self.drifted_preferences

        return prefs.get(
            template_code,
            ArmPreference(p_accept=0.3, p_complete=0.5, p_helpful=0.6),
        )

    def best_fixed_arm(self, total_weeks: int = 52) -> tuple[str, float]:
        """Determine best fixed template arm in hindsight and its average weekly expected reward."""
        all_templates = set(self.preferences.keys()) | set(self.drifted_preferences.keys())
        best_template = ""
        best_avg_reward = -1.0

        for tmpl in all_templates:
            total_expected = 0.0
            for w in range(1, total_weeks + 1):
                pref = self.get_preference(tmpl, w)
                total_expected += pref.expected_reward
            avg_rew = total_expected / float(total_weeks)
            if avg_rew > best_avg_reward:
                best_avg_reward = avg_rew
                best_template = tmpl

        return best_template, best_avg_reward

    def best_fixed_slate(
        self, total_weeks: int = 52, slate_size: int = 3
    ) -> tuple[list[str], float]:
        """Determine best fixed slate of distinct arms in hindsight and total expected reward."""
        all_templates = set(self.preferences.keys()) | set(self.drifted_preferences.keys())
        arm_rewards: list[tuple[str, float]] = []

        for tmpl in all_templates:
            total_expected = 0.0
            for w in range(1, total_weeks + 1):
                pref = self.get_preference(tmpl, w)
                total_expected += pref.expected_reward
            arm_rewards.append((tmpl, total_expected))

        arm_rewards.sort(key=lambda x: x[1], reverse=True)
        top_arms = arm_rewards[:slate_size]
        slate_codes = [a[0] for a in top_arms]
        slate_total_reward = sum(a[1] for a in top_arms)
        return slate_codes, slate_total_reward


def get_default_personas() -> dict[str, Persona]:
    """Return preconfigured standard simulation personas."""
    # 1. ThriftyCook: Loves dining reduction, dislikes commute cuts
    thrifty_cook = Persona(
        name="ThriftyCook",
        description="Enjoys cooking at home; eager to cut weekend dining and food delivery.",
        preferences={
            "tpl_dining_weekend": ArmPreference(p_accept=0.9, p_complete=0.85, p_helpful=0.9),
            "tpl_delivery_cap": ArmPreference(p_accept=0.85, p_complete=0.8, p_helpful=0.85),
            "tpl_no_spend_day": ArmPreference(p_accept=0.6, p_complete=0.6, p_helpful=0.7),
            "tpl_grocery_smart": ArmPreference(p_accept=0.4, p_complete=0.5, p_helpful=0.5),
            "tpl_commute_transit": ArmPreference(p_accept=0.1, p_complete=0.2, p_helpful=0.3),
            "tpl_subscription_audit": ArmPreference(p_accept=0.5, p_complete=0.7, p_helpful=0.8),
        },
        drift_after_week=26,
        drifted_preferences={
            "tpl_dining_weekend": ArmPreference(p_accept=0.85, p_complete=0.8, p_helpful=0.85),
            "tpl_delivery_cap": ArmPreference(p_accept=0.8, p_complete=0.75, p_helpful=0.8),
            "tpl_no_spend_day": ArmPreference(p_accept=0.7, p_complete=0.7, p_helpful=0.8),
            "tpl_grocery_smart": ArmPreference(p_accept=0.5, p_complete=0.6, p_helpful=0.6),
            "tpl_commute_transit": ArmPreference(p_accept=0.1, p_complete=0.2, p_helpful=0.3),
            "tpl_subscription_audit": ArmPreference(p_accept=0.3, p_complete=0.5, p_helpful=0.6),
        },
    )

    # 2. BusyCommuter: Relies on delivery, likes subscriptions and commute transit
    busy_commuter = Persona(
        name="BusyCommuter",
        description="Time-poor professional; open to transit and subscription audits.",
        preferences={
            "tpl_commute_transit": ArmPreference(p_accept=0.85, p_complete=0.8, p_helpful=0.85),
            "tpl_subscription_audit": ArmPreference(p_accept=0.8, p_complete=0.85, p_helpful=0.9),
            "tpl_delivery_cap": ArmPreference(p_accept=0.2, p_complete=0.3, p_helpful=0.3),
            "tpl_dining_weekend": ArmPreference(p_accept=0.3, p_complete=0.3, p_helpful=0.4),
            "tpl_no_spend_day": ArmPreference(p_accept=0.3, p_complete=0.4, p_helpful=0.5),
            "tpl_grocery_smart": ArmPreference(p_accept=0.2, p_complete=0.3, p_helpful=0.4),
        },
        drift_after_week=26,
        drifted_preferences={
            "tpl_commute_transit": ArmPreference(p_accept=0.75, p_complete=0.75, p_helpful=0.8),
            "tpl_subscription_audit": ArmPreference(p_accept=0.6, p_complete=0.7, p_helpful=0.8),
            "tpl_delivery_cap": ArmPreference(p_accept=0.3, p_complete=0.4, p_helpful=0.4),
            "tpl_dining_weekend": ArmPreference(p_accept=0.4, p_complete=0.4, p_helpful=0.5),
            "tpl_no_spend_day": ArmPreference(p_accept=0.4, p_complete=0.5, p_helpful=0.6),
            "tpl_grocery_smart": ArmPreference(p_accept=0.3, p_complete=0.4, p_helpful=0.5),
        },
    )

    # 3. FickleDrifter: Initially excited about no-spend days, then drifts away
    fickle_drifter = Persona(
        name="FickleDrifter",
        description="Novelty-seeking user whose challenge preferences shift over time.",
        preferences={
            "tpl_no_spend_day": ArmPreference(p_accept=0.9, p_complete=0.8, p_helpful=0.85),
            "tpl_dining_weekend": ArmPreference(p_accept=0.7, p_complete=0.6, p_helpful=0.7),
            "tpl_delivery_cap": ArmPreference(p_accept=0.5, p_complete=0.5, p_helpful=0.5),
            "tpl_subscription_audit": ArmPreference(p_accept=0.4, p_complete=0.5, p_helpful=0.6),
            "tpl_commute_transit": ArmPreference(p_accept=0.3, p_complete=0.3, p_helpful=0.4),
        },
        drift_after_week=26,
        drifted_preferences={
            "tpl_no_spend_day": ArmPreference(p_accept=0.25, p_complete=0.3, p_helpful=0.4),
            "tpl_dining_weekend": ArmPreference(p_accept=0.3, p_complete=0.3, p_helpful=0.4),
            "tpl_delivery_cap": ArmPreference(p_accept=0.8, p_complete=0.75, p_helpful=0.8),
            "tpl_subscription_audit": ArmPreference(p_accept=0.7, p_complete=0.8, p_helpful=0.85),
            "tpl_commute_transit": ArmPreference(p_accept=0.4, p_complete=0.4, p_helpful=0.5),
        },
    )

    return {
        "ThriftyCook": thrifty_cook,
        "BusyCommuter": busy_commuter,
        "FickleDrifter": fickle_drifter,
    }
