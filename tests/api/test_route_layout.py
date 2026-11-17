"""Every route is reachable: no fixed path sits behind an earlier `{param}` path of the same method."""

import re

from copilot.api.app import create_app
from copilot.api.state import ApiState


def test_no_route_is_shadowed_by_an_earlier_parameterised_one(tmp_path):
    app = create_app(ApiState(db_path=tmp_path / "x.db", llm=None))
    seen: list[tuple[str, str]] = []
    shadowed = []
    for route in app.routes:
        for method in getattr(route, "methods", None) or ():
            for m, earlier in seen:
                if m == method and "{" in earlier and earlier != route.path:
                    pattern = "^" + re.sub(r"\{[^}]+\}", "[^/]+", earlier) + "$"
                    if re.match(pattern, route.path):
                        shadowed.append(f"{method} {route.path} (behind {earlier})")
            seen.append((method, route.path))
    assert shadowed == []


def test_every_area_registers_at_least_one_route(tmp_path):
    from copilot.api import routes

    app = create_app(ApiState(db_path=tmp_path / "x.db", llm=None))
    owners = {getattr(r, "endpoint", None).__module__ for r in app.routes if hasattr(r, "endpoint")}
    assert {area.__name__ for area in routes.AREAS} <= owners
