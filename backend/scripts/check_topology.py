"""Validate the merged deployment model without contacting a Docker daemon."""

import json, os, shlex, subprocess
from pathlib import Path

root = Path(__file__).parents[2]
command = shlex.split(os.getenv("COMPOSE_COMMAND", "docker compose"))
raw = subprocess.check_output(
    command
    + ["-f", "compose.yaml", "-f", "compose.public-test.yaml", "config", "--format", "json"],
    cwd=root,
)
services = json.loads(raw)["services"]
for name in ("api", "api-secondary"):
    assert not services[name].get("ports"), f"{name} must not bypass gateway"
for name, partitions in [
    ("worker", "0,1,2,3,4,5,6,7"),
    ("worker-secondary", "8,9,10,11,12,13,14,15"),
]:
    assert services[name]["environment"]["WORKER_PARTITIONS"] == partitions
    assert services[name]["environment"]["DB_POOL_SIZE"] == "2"
    assert "DATABASE_URL" in services[name]["environment"]
assert services["gateway"]["ports"][0]["host_ip"] == "127.0.0.1"
print(
    "Compose topology validated: two private API replicas, complementary worker partitions, bounded pools, single loopback gateway."
)
