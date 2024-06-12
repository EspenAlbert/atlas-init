#!/usr/bin/env bash
set -euo pipefail
repo_root=$(git rev-parse --show-toplevel)
export PYTHONPATH=$repo_root/py
cd $PYTHONPATH
hatch fmt
hatch run default:fmt_config
echo "pre-commit-ok!"