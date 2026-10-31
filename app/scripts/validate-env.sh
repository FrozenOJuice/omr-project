#!/bin/sh
set -eu

env_file=$1
shift

if [ ! -f "$env_file" ]; then
    echo "Missing $env_file. Run the matching setup target first." >&2
    exit 1
fi

missing=""
for key in "$@"; do
    value=$(sed -n "s/^${key}=//p" "$env_file" | tail -n 1)
    if [ -z "$value" ]; then
        missing="$missing $key"
    fi
done

if [ -n "$missing" ]; then
    echo "Missing required values in $env_file:$missing" >&2
    exit 1
fi
