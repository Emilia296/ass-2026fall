"""Regenerate the route inventory from the supplied authoritative API document."""

import json, re
from pathlib import Path

root = Path(__file__).resolve().parents[2]
text = (root / "接口文档.md").read_text(encoding="utf-8")
title = ""
routes = []
for line in text.splitlines():
    if line.startswith("## "):
        title = line.removeprefix("## ")
    match = re.match(r"\*\*(GET|POST|PUT|DELETE)\*\* `([^`]+)`", line)
    if match:
        routes.append({"method": match[1], "path": match[2], "title": title})
(root / "backend/api-contract.json").write_text(
    json.dumps(routes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"{len(routes)} documented endpoints")
