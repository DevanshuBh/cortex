"""Write the API's OpenAPI document to web/openapi.json (the front end generates its types from it)."""

from __future__ import annotations

import json
from pathlib import Path

from cortex.api.main import app

out = Path(__file__).resolve().parents[2] / "web" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=1) + "\n", encoding="utf-8")
print(f"wrote {out}")
