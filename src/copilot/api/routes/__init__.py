"""
The HTTP routes, one module per area of the product. Each module has a `register(app, state)`
that adds its routes; `copilot.api.app.create_app` calls them in the order below.
"""

from copilot.api.routes import (
    ask,
    banklink,
    capture,
    engagement,
    ledger,
    memory,
    ops,
    personal,
    planning,
    review,
    session,
)

AREAS = (
    session,
    ledger,
    review,
    ask,
    planning,
    memory,
    ops,
    engagement,
    capture,
    banklink,
    personal,
)
