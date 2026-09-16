#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
venv_dir=${CHARGE_VENV:-$HOME/charge-venv}
cd "$project_dir/backend"
"$venv_dir/bin/python" -m pytest -q "$@"
