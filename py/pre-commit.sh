#!/usr/bin/env bash
set -euo pipefail
repo_root=$(git rev-parse --show-toplevel)
echo "running from $repo_root"
PYTHONPATH=$repo_root/py
echo "PYTHONPATH=$PYTHONPATH"
cd $PYTHONPATH
hatch fmt
echo "Files are formatted ✅"
hatch run default:fmt_config
echo "pre-commit-ok!"