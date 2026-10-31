#!/usr/bin/env bash
set -euo pipefail

canvas_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$canvas_dir/.env"

if [[ ! -f "$env_file" ]]; then
  echo "Canvas is not configured. Run 'make canvas-setup' first." >&2
  exit 1
fi

# Bash 3.2 (the version shipped with macOS) raises an "unbound variable"
# error when an empty array is expanded while nounset is enabled. Keep the
# optional build flag on separate execution paths so every supported Bash
# version receives only initialized arguments.
if [[ " $* " == *" build "* ]]; then
  exec docker compose --progress=plain --env-file "$env_file" -f "$canvas_dir/docker-compose.yml" "$@"
fi

exec docker compose --env-file "$env_file" -f "$canvas_dir/docker-compose.yml" "$@"
