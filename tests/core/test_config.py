import inspect

import pytest
from pydantic import ValidationError

from copilot.core.config import DEFAULT_SETTINGS_PATH, PROJECT_ROOT, load_settings
from copilot.core.timeutil import IST
from copilot.governance.policy import load_policy
from copilot.llm.client import structured_call
from copilot.tools.financial import forecast_category_spend_handler

GOOD = """
timezone: Asia/Kolkata
currency: INR
db_path: data/x.db
policy_path: config/policy.yaml
default_warn_threshold_pct: 80
forecast_method: run_rate
llm_max_retries: 2
categorization_rules_path: config/categorization_rules.yaml
merchant_aliases_path: config/merchant_aliases.yaml
advice_templates_path: config/advice_templates.yaml
"""


def test_repo_settings_load():
    settings = load_settings()
    assert settings.db_path == PROJECT_ROOT / "data" / "copilot.db"
    assert settings.policy_path.exists()
    load_policy(settings.policy_path)  # the configured policy is valid


def test_settings_agree_with_code():
    settings = load_settings()
    assert settings.timezone == IST.key
    assert settings.forecast_method in inspect.getsource(forecast_category_spend_handler)
    default_retries = inspect.signature(structured_call).parameters["max_retries"].default
    assert settings.llm_max_retries == default_retries


def test_absolute_paths_kept(tmp_path):
    f = tmp_path / "s.yaml"
    f.write_text(GOOD.replace("data/x.db", str(tmp_path / "abs.db")), encoding="utf-8")
    assert load_settings(f).db_path == tmp_path / "abs.db"


@pytest.mark.parametrize(
    "old, new",
    [
        ("Asia/Kolkata", "UTC"),
        ("INR", "USD"),
        ("run_rate", "prophet"),
        ("default_warn_threshold_pct: 80", "default_warn_threshold_pct: 120"),
        ("llm_max_retries: 2", "llm_max_retries: 2\nsurprise: 1"),
    ],
)
def test_bad_settings_rejected(tmp_path, old, new):
    f = tmp_path / "s.yaml"
    f.write_text(GOOD.replace(old, new), encoding="utf-8")
    with pytest.raises(ValidationError):
        load_settings(f)


def test_default_path_points_at_repo_config():
    assert DEFAULT_SETTINGS_PATH == PROJECT_ROOT / "config" / "settings.yaml"
