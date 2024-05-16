#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH=$(pwd)/py
cd py
hatch fmt
hatch run default:fmt_config
echo "pre-commit-ok!"