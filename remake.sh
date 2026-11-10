#!/usr/bin/env bash
# Runs Remake Studio with its own virtualenv (created by ./setup.sh).
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${REMAKE_PYTHON:-$HERE/.venv/bin/python}"
cd "$HERE" && PYTHONWARNINGS=ignore exec "$PY" -m remake "$@"
