#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

canvas_dir="$tmp_dir/Canvas project/canvas"
bin_dir="$tmp_dir/bin"
mkdir -p "$canvas_dir/scripts" "$bin_dir"
cp "$script_dir/compose.sh" "$script_dir/seed.sh" "$script_dir/wait-for-canvas.sh" "$canvas_dir/scripts/"
printf '# test seed\n' > "$canvas_dir/scripts/seed.rb"
touch "$canvas_dir/.env" "$canvas_dir/docker-compose.yml"

cat > "$bin_dir/docker" <<'SH'
#!/usr/bin/env sh
printf '%s\n' "$@" > "$CANVAS_TEST_ARGS_FILE"
SH
chmod +x "$bin_dir/docker"

assert_line() {
  local expected="$1"
  local line_number="$2"
  local actual
  actual="$(sed -n "${line_number}p" "$CANVAS_TEST_ARGS_FILE")"
  if [[ "$actual" != "$expected" ]]; then
    echo "Expected argument ${line_number} to be '${expected}', got '${actual}'." >&2
    exit 1
  fi
}

export CANVAS_TEST_ARGS_FILE="$tmp_dir/compose-args"
PATH="$bin_dir:$PATH" "$BASH" "$canvas_dir/scripts/compose.sh" down --remove-orphans
assert_line "compose" 1
assert_line "--env-file" 2
assert_line "$canvas_dir/.env" 3
assert_line "-f" 4
assert_line "$canvas_dir/docker-compose.yml" 5
assert_line "down" 6
assert_line "--remove-orphans" 7
[[ "$(wc -l < "$CANVAS_TEST_ARGS_FILE" | tr -d ' ')" == "7" ]]

PATH="$bin_dir:$PATH" "$BASH" "$canvas_dir/scripts/compose.sh" build web
assert_line "compose" 1
assert_line "--progress=plain" 2
assert_line "--env-file" 3
assert_line "$canvas_dir/.env" 4
assert_line "-f" 5
assert_line "$canvas_dir/docker-compose.yml" 6
assert_line "build" 7
assert_line "web" 8
[[ "$(wc -l < "$CANVAS_TEST_ARGS_FILE" | tr -d ' ')" == "8" ]]

cat > "$canvas_dir/.env" <<'ENV'
CANVAS_HOST=localhost:6700
CANVAS_PROFESSOR_NAME="Avery Brooks"
CANVAS_PROFESSOR_EMAIL=empty.prof@example.com
CANVAS_PROFESSOR_SIS_ID=professor-001
CANVAS_TEST_PASSWORD=Password123!
CANVAS_API_TOKEN=test-api-token
ENV
cat > "$bin_dir/curl" <<'SH'
#!/usr/bin/env sh
exit 0
SH
cat > "$bin_dir/seq" <<'SH'
#!/usr/bin/env sh
echo "wait-for-canvas.sh must not depend on seq" >&2
exit 99
SH
chmod +x "$bin_dir/curl" "$bin_dir/seq"

PATH="$bin_dir:$PATH" "$BASH" "$canvas_dir/scripts/wait-for-canvas.sh" >/dev/null

cat > "$canvas_dir/scripts/smoke-test.sh" <<'SH'
#!/usr/bin/env sh
exit 0
SH
chmod +x "$canvas_dir/scripts/smoke-test.sh"

rm -f "$CANVAS_TEST_ARGS_FILE"
PATH="$bin_dir:$PATH" "$BASH" "$canvas_dir/scripts/seed.sh" >/dev/null
assert_line "run" 6
assert_line "--rm" 7
assert_line "web" 8
assert_line "bin/rails" 9
assert_line "runner" 10
assert_line "script/capstone_seed.rb" 11
[[ -f "$canvas_dir/.seed-state" ]]

# An unchanged, healthy seed uses the fast path without invoking Docker.
rm -f "$CANVAS_TEST_ARGS_FILE"
PATH="$bin_dir:$PATH" "$BASH" "$canvas_dir/scripts/seed.sh" >/dev/null
[[ ! -e "$CANVAS_TEST_ARGS_FILE" ]]

# Changing the seed invalidates the marker and runs the full reconciler.
printf '# changed seed\n' >> "$canvas_dir/scripts/seed.rb"
PATH="$bin_dir:$PATH" "$BASH" "$canvas_dir/scripts/seed.sh" >/dev/null
assert_line "run" 6

# FORCE=true's wrapper argument always bypasses the marker.
rm -f "$CANVAS_TEST_ARGS_FILE"
PATH="$bin_dir:$PATH" "$BASH" "$canvas_dir/scripts/seed.sh" --force >/dev/null
assert_line "run" 6

echo "Canvas script portability checks passed with Bash ${BASH_VERSION}."
