"""Suite-wide safeguards.

* Several fixtures call `clear_registry()` to start from a clean tool registry. Without a guard
  they leave the process-wide registry empty or partial for whichever test runs next, so a
  test's result depended on which directories ran before it. Each test now ends with the
  registry exactly as it began.
* No test can reach a real language-model provider by accident (PLAN_PHASE4 section 0.8.6). The
  model is switched off by default and any outbound HTTP call fails the test. Tests that
  genuinely need a live provider are marked `@pytest.mark.live`, are skipped, and only run with
  `--live`. A live run is capped by `LIVE_MAX_CALLS` (default 20).
"""

import os
import urllib.request

import pytest

from copilot.tools import registry

LIVE_MAX_CALLS = int(os.environ.get("LIVE_MAX_CALLS", "20"))


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False, help="run live-provider tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: calls a real model provider (needs --live)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="live provider test: run with --live")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _restore_tool_registry():
    """Whatever a test does to the tool registry, the next test sees the original."""
    before = dict(registry._registry)  # noqa: SLF001 - the registry is a test seam here
    yield
    registry._registry.clear()  # noqa: SLF001
    registry._registry.update(before)  # noqa: SLF001


@pytest.fixture(autouse=True)
def _no_real_model_or_network(request, monkeypatch):
    """The model stays off and outbound HTTP fails, unless the test is marked live."""
    if request.node.get_closest_marker("live"):
        return
    monkeypatch.setenv("FINCO_LLM", "off")
    # Older tests script a model client for the rules-first path. The model-first path has its
    # own tests, which switch it on explicitly.
    monkeypatch.setenv("FINCO_LLM_PRIMARY", "0")

    def _blocked(*args, **kwargs):
        raise AssertionError(
            "A test tried to make a real network call. Use a fake client or transport, "
            "or mark the test @pytest.mark.live."
        )

    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
