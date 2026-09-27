"""Export the backend OpenAPI schema to openapi.json (repository root).

Usage:  .venv/bin/python -m scripts.export_openapi
Consumed by `npm run gen:api` in frontend/ to regenerate src/lib/api.gen.ts.
The json is a build artifact (gitignored); the generated .ts IS committed.
"""

import json
from pathlib import Path

from backend.app import app

out = Path(__file__).resolve().parent.parent / "openapi.json"
out.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=1))
print(f"openapi.json exported ({out.stat().st_size} bytes)")
