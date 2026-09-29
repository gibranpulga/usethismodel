#!/usr/bin/env bash
# Cron entry point. flock covers fetch, backup, validation, commit, and push.
set -euo pipefail
umask 077
UPDATER_ROOT="${UPDATER_ROOT:-$HOME/usethismodel-updater}"
mkdir -p "$UPDATER_ROOT/state"
exec 9>"$UPDATER_ROOT/state/update.lock"
flock -n 9 || exit 0
exec "$UPDATER_ROOT/.venv/bin/python" "$UPDATER_ROOT/repo/scripts/daily_update.py" \
  --root "$UPDATER_ROOT" "$@"
