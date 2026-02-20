#!/usr/bin/env bash
# Clean Architecture Prompt Hook
# Runs before Claude processes any user prompt to inject architectural context
# so that planning and implementation both consider clean architecture.

cat <<'CONTEXT'
CLEAN ARCHITECTURE CONTEXT: This codebase follows Clean Architecture. All changes must respect the dependency rule.

LAYER HIERARCHY (dependencies point inward only):
  controllers/ (outer) -> use_cases/ (middle) -> entities/ (inner)
  repos/ implements interfaces defined by use_cases/
  tools/ are standalone infrastructure utilities

KEY RULES:
- entities/: Zero dependencies. Pure domain logic and business invariants.
- use_cases/: Depends only on entities/. Defines output port interfaces. Dependencies injected via parameters.
- controllers/: Calls use_cases/. No business logic. No direct repo or infrastructure access.
- repos/: Implements use case interfaces. May use external libraries (Docker SDK, file I/O).
- tools/: Infrastructure utilities. No business logic. No use_case or controller imports.
- bootstrap.py / index.py: Composition root. Only place where concrete implementations are wired together.

When planning changes, identify which layer(s) will be affected and ensure no dependency violations are introduced.
CONTEXT
