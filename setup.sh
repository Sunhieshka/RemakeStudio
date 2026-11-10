#!/usr/bin/env bash
# One-time setup: virtualenv + dependencies + .env from the template.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
[ -f .env ] || { cp .env.example .env; echo "Created .env — fill in your BytePlus credentials."; }
echo "Done. Run ./remake.sh serve"
