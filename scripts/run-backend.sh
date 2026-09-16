#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
venv_dir=${CHARGE_VENV:-$HOME/charge-venv}
cd "$project_dir/backend"
if [[ ! -x "$venv_dir/bin/python" ]]; then
  python3 -m venv "$venv_dir"
  "$venv_dir/bin/pip" install -r requirements.txt
fi
mkdir -p "$project_dir/.runtime"
exec 9>"$project_dir/.runtime/backend.lock"
if ! flock -n 9; then echo 'Backend supervisor is already running.'; exit 1; fi
"$venv_dir/bin/python" -m app.seed
pids=()
printf '%s\n' "$$" > "$project_dir/.runtime/supervisor.pid"
cleanup() {
  trap - EXIT INT TERM
  for task_pid in "${pids[@]}"; do kill "$task_pid" 2>/dev/null || true; done
  wait || true
}
trap cleanup EXIT INT TERM
"$venv_dir/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 2 --limit-concurrency 500 > "$project_dir/.runtime/api.log" 2>&1 &
pids+=("$!")
"$venv_dir/bin/python" -m app.worker > "$project_dir/.runtime/worker.log" 2>&1 &
pids+=("$!")
"$venv_dir/bin/python" -m app.simulator > "$project_dir/.runtime/simulator.log" 2>&1 &
pids+=("$!")
echo 'API: http://localhost:8080/docs | Logs: .runtime/'
wait -n
