#!/usr/bin/env bash
# Restart the MkDocs dev server, killing any existing instance first.
set -e

PORT="${1:-8000}"
HOST="${2:-0.0.0.0}"

# Kill any existing mkdocs process
for pid in $(ls /proc 2>/dev/null | grep -E '^[0-9]+$'); do
  if cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ' | grep -q mkdocs; then
    kill -9 "$pid" 2>/dev/null || true
  fi
done
sleep 1

exec uv run mkdocs serve -a "$HOST:$PORT"
