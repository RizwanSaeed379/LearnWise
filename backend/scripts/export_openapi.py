"""Write the OpenAPI spec generated from the code to docs/openapi.json.

Run from backend/:  python scripts/export_openapi.py
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from app.main import app  # noqa: E402

out = pathlib.Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=2))
print(f"wrote {out}")
