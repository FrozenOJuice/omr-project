#!/usr/bin/env bash
set -euo pipefail

canvas_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$canvas_dir/.env"
checkout="$canvas_dir/canvas-lms"
# Use $BASH (the interpreter this script itself is running under) rather
# than a bare `bash`. Non-interactive script execution doesn't source
# .bashrc, so on machines where the raw Windows PATH lists System32
# (legacy WSL-launcher stub) ahead of Git's real bash.exe, a bare `bash`
# resolves to the broken stub even from inside a correctly-launched bash.
compose=("$BASH" "$canvas_dir/scripts/compose.sh")

replace_setting() {
  local key="$1"
  local value="$2"
  KEY="$key" VALUE="$value" perl -pi -e 's/^\Q$ENV{KEY}\E=.*/$ENV{KEY}=$ENV{VALUE}/' "$env_file"
}

created_env=false
if [[ ! -f "$env_file" ]]; then
  cp "$canvas_dir/.env.example" "$env_file"
  created_env=true
fi

for key in CANVAS_ENCRYPTION_KEY CANVAS_JWT_ENCRYPTION_KEY CANVAS_API_TOKEN; do
  if grep -q "^${key}=generate-me$" "$env_file"; then
    replace_setting "$key" "$(openssl rand -hex 32)"
  fi
done
chmod 600 "$env_file"
if $created_env; then
  echo "Created tools/canvas/.env with local-only credentials."
fi

# shellcheck disable=SC1090
source "$env_file"

if [[ ! -d "$checkout/.git" ]]; then
  echo "Cloning Canvas LMS ${CANVAS_LMS_REF}..."
  # -c core.autocrlf=false: Canvas ships Ruby/shell scripts with LF shebangs
  # that must stay LF for the Linux build container, regardless of the
  # user's global git config (Windows commonly defaults autocrlf=true).
  git -c core.autocrlf=false clone --depth 1 --branch "$CANVAS_LMS_REF" https://github.com/instructure/canvas-lms.git "$checkout"
fi

if [[ "$(git -C "$checkout" rev-parse HEAD)" != "$CANVAS_LMS_SHA" ]]; then
  echo "Checking out pinned Canvas revision ${CANVAS_LMS_SHA}..."
  git -C "$checkout" fetch --depth 1 origin "refs/tags/${CANVAS_LMS_REF}:refs/tags/${CANVAS_LMS_REF}"
  git -C "$checkout" checkout --detach "$CANVAS_LMS_SHA"
fi

if [[ "$(git -C "$checkout" rev-parse HEAD)" != "$CANVAS_LMS_SHA" ]]; then
  echo "Canvas checkout does not match the configured revision." >&2
  exit 1
fi

echo "Building Canvas. The first build can take a while..."
"${compose[@]}" build web
"${compose[@]}" up -d postgres redis

echo "Creating and migrating the Canvas database..."
"${compose[@]}" run --rm -e UPDATE_ENCRYPTION_KEY_HASH=1 web bin/rails db:create db:migrate

echo "Loading Canvas defaults and the local administrator..."
"${compose[@]}" run --rm -e UPDATE_ENCRYPTION_KEY_HASH=1 web bin/rails db:initial_setup brand_configs:generate_and_upload_all

echo "Creating the professor, students, courses, assignments, and API token..."
"$BASH" "$canvas_dir/scripts/seed.sh" --force

"${compose[@]}" up -d
"$BASH" "$canvas_dir/scripts/wait-for-canvas.sh"
"$BASH" "$canvas_dir/scripts/smoke-test.sh"

echo
echo "Canvas is ready at http://${CANVAS_HOST}"
echo "Professor login: ${CANVAS_PROFESSOR_EMAIL}"
echo "Password: ${CANVAS_TEST_PASSWORD}"
