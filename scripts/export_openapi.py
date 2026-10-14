"""Write docs/openapi.json from the API app (used to generate frontend/src/api/schema.d.ts)."""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot.api.app import create_app  # noqa: E402
from copilot.api.state import ApiState  # noqa: E402

state = ApiState(db_path=Path(tempfile.gettempdir()) / "finco_openapi.db", token="x")
schema = create_app(state).openapi()
# Responses always include every field (defaults are serialised), so mark them required for the
# generated TypeScript types. Request bodies (names ending in "In") keep their optional fields.
for name, definition in schema["components"]["schemas"].items():
    props = definition.get("properties")
    if props and not name.endswith("In") and not name.startswith("Body_"):
        definition["required"] = sorted(props)
out = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
out.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {out} ({len(schema['paths'])} paths)")
