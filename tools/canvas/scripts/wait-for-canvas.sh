#!/usr/bin/env bash
set -euo pipefail

canvas_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# shellcheck disable=SC1091
source "$canvas_dir/.env"

url="http://${CANVAS_HOST}/login/canvas"
# macOS does not include `seq` by default. Bash's arithmetic loop works in
# the stock macOS Bash 3.2 as well as Linux and Git Bash on Windows.
for ((attempt = 1; attempt <= 180; attempt++)); do
  if curl --fail --silent "$url" >/dev/null; then
    echo "Canvas is accepting requests."
    exit 0
  fi

  if (( attempt % 10 == 0 )); then
    echo "Waiting for Canvas to start (attempt ${attempt}/180)..."
  fi
  sleep 2
done

echo "Canvas did not become ready. Run 'make canvas-logs' for details." >&2
exit 1
