#!/usr/bin/env bash
set -euo pipefail
cd py
hatch fmt

echo "pre-commit-ok!"