#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
sudo apt-get update
sudo apt-get install -y python3-venv postgresql redis-server
sudo service postgresql start
sudo service redis-server start
if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='charge'" | grep -q 1; then
  sudo -u postgres psql -v ON_ERROR_STOP=1 -c "CREATE ROLE charge LOGIN PASSWORD 'charge' CREATEDB"
fi
for db_name in charge charge_test; do
  if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$db_name'" | grep -q 1; then
    sudo -u postgres createdb --owner=charge "$db_name"
  fi
done
venv_dir=${CHARGE_VENV:-$HOME/charge-venv}
python3 -m venv "$venv_dir"
"$venv_dir/bin/pip" install -r "$project_dir/backend/requirements.txt"
cd "$project_dir/backend"
"$venv_dir/bin/python" -m app.seed
echo 'Setup complete. Run bash scripts/run-backend.sh from the project root.'
