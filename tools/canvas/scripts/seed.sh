#!/usr/bin/env bash
set -euo pipefail

canvas_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$canvas_dir/.env"
marker_file="$canvas_dir/.seed-state"
seed_file="$canvas_dir/scripts/seed.rb"
compose=("$BASH" "$canvas_dir/scripts/compose.sh")

if [[ ! -f "$env_file" ]]; then
  echo "Canvas is not configured. Run 'make canvas-setup' first." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$env_file"

force=false
if [[ "${1:-}" == "--force" ]]; then
  force=true
elif [[ $# -gt 0 ]]; then
  echo "Usage: $0 [--force]" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
fingerprint_input="$tmp_dir/fingerprint"
{
  cat "$seed_file"
  printf '\n%s\n' \
    "$(date -u +%Y)" \
    "$CANVAS_PROFESSOR_NAME" \
    "$CANVAS_PROFESSOR_EMAIL" \
    "$CANVAS_PROFESSOR_SIS_ID" \
    "$CANVAS_TEST_PASSWORD" \
    "$CANVAS_API_TOKEN"
} > "$fingerprint_input"

if command -v sha256sum >/dev/null 2>&1; then
  fingerprint="$(sha256sum "$fingerprint_input" | awk '{print $1}')"
else
  fingerprint="$(shasum -a 256 "$fingerprint_input" | awk '{print $1}')"
fi

if ! $force && [[ -f "$marker_file" ]] && [[ "$(tr -d '\r\n' < "$marker_file")" == "$fingerprint" ]]; then
  if "$BASH" "$canvas_dir/scripts/smoke-test.sh" >/dev/null 2>&1; then
    echo "Canvas presentation data is already current; skipped the Rails seed."
    exit 0
  fi
  echo "Canvas presentation data check failed; running the full Rails seed..."
fi

"${compose[@]}" run --rm web bin/rails runner script/capstone_seed.rb
printf '%s\n' "$fingerprint" > "$marker_file"
chmod 600 "$marker_file"
