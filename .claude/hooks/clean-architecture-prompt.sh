#!/usr/bin/env bash
# Clean Architecture Prompt Hook
# Runs before Claude processes any user prompt to inject architectural context
# so that planning and implementation both consider clean architecture.

set -euo pipefail

cat <<'CONTEXT'
{
  "hookSpecificOutput": {
    "additionalContext": "CLEAN ARCHITECTURE CONTEXT: This codebase follows Clean Architecture. All changes must respect the dependency rule.\n\nLAYER HIERARCHY (dependencies point inward only):\n  controllers/ (outer) -> use_cases/ (middle) -> entities/ (inner)\n  repos/ implements interfaces defined by use_cases/\n  tools/ are standalone infrastructure utilities\n\nKEY RULES:\n- entities/: Zero dependencies. Pure domain logic and business invariants.\n- use_cases/: Depends only on entities/. Defines output port interfaces. Dependencies injected via parameters.\n- controllers/: Calls use_cases/. No business logic. No direct repo or infrastructure access.\n- repos/: Implements use case interfaces. May use external libraries (Docker SDK, file I/O).\n- tools/: Infrastructure utilities. No business logic. No use_case or controller imports.\n- bootstrap.py / index.py: Composition root. Only place where concrete implementations are wired together.\n\nWhen planning changes, identify which layer(s) will be affected and ensure no dependency violations are introduced."
  }
}
CONTEXT
