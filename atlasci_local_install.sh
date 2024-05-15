#!/usr/bin/env bash

set -euo pipefail

uv venv -p 3.12 .venv
source ./.venv/bin/activate
cd py
hatch build -t wheel --clean-hooks-after
cd ..
uv pip install -U --find-links py/dist atlas-init --no-cache --reinstall-package atlas-init