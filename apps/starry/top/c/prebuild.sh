#!/bin/sh
set -eu

apk add procps

if ! command -v top >/dev/null 2>&1; then
    echo "missing procps top after installation" >&2
    exit 1
fi
