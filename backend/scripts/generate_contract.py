"""Validate the checked-in API route inventory used to build OpenAPI."""

import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
contract_path = root / "backend/api-contract.json"
routes = json.loads(contract_path.read_text(encoding="utf-8"))
if not isinstance(routes, list) or not all(
    isinstance(item, dict) and {"method", "path", "title"} <= item.keys() for item in routes
):
    raise SystemExit("backend/api-contract.json is not a valid route inventory")
print(f"{len(routes)} API endpoints in {contract_path.name}")
