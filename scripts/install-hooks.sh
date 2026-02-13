#!/usr/bin/env bash
# Install git hooks by setting core.hooksPath to scripts/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

git -C "$REPO_ROOT" config core.hooksPath scripts
echo "Git hooks installed (core.hooksPath → scripts/)."
