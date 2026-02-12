#!/usr/bin/env bash
# Clean Architecture Guard Hook
# Runs before Edit/Write tool calls to remind Claude about architectural rules.
# Reads the tool input from stdin and outputs architectural context.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Only apply to source files
case "$FILE_PATH" in
    */src/*) ;;
    *) exit 0 ;;
esac

# Determine which layer this file belongs to
LAYER=""
case "$FILE_PATH" in
    */entities/*)    LAYER="entities" ;;
    */use_cases/*)   LAYER="use_cases" ;;
    */controllers/*) LAYER="controllers" ;;
    */repos/*)       LAYER="repos" ;;
    */tools/*)       LAYER="tools" ;;
    */index.py)      LAYER="entry_point" ;;
esac

if [ -z "$LAYER" ]; then
    exit 0
fi

# Build layer-specific guidance
CONTEXT="CLEAN ARCHITECTURE GUARD: You are editing a file in the '$LAYER' layer."

case "$LAYER" in
    entities)
        CONTEXT="$CONTEXT
- Entities are the INNERMOST layer. They must have ZERO dependencies on other layers.
- No imports from use_cases/, controllers/, repos/, or tools/.
- Entities enforce business invariants and contain domain logic only."
        ;;
    use_cases)
        CONTEXT="$CONTEXT
- Use cases may depend on entities but NEVER on controllers/, repos/ implementations, or tools/.
- Use cases define output port INTERFACES (abstract classes) that repos implement.
- Dependencies (repos, gateways) must be INJECTED via parameters, not imported directly.
- Each use case orchestrates one specific application action."
        ;;
    controllers)
        CONTEXT="$CONTEXT
- Controllers are the OUTER layer (interface adapters). They may import from use_cases/.
- Controllers receive external input and call use cases. They must NOT contain business logic.
- Controllers must NOT directly access repos/ or Docker/database APIs."
        ;;
    repos)
        CONTEXT="$CONTEXT
- Repos are interface adapters (secondary/driven). They implement use case output port interfaces.
- Repos may import from entities/ and external libraries (Docker SDK, file I/O, etc.).
- Repos must NOT import from use_cases/ or controllers/."
        ;;
    tools)
        CONTEXT="$CONTEXT
- Tools are infrastructure utilities. They must NOT contain business logic.
- Tools must NOT import from use_cases/ or controllers/.
- Tools provide cross-cutting concerns: logging, validation, system metrics."
        ;;
    entry_point)
        CONTEXT="$CONTEXT
- This is the composition root. Dependency wiring happens here or in bootstrap.py.
- This is the ONLY place where concrete implementations are instantiated and connected."
        ;;
esac

CONTEXT="$CONTEXT
DEPENDENCY RULE: Source code dependencies must point ONLY inward.
  controllers/ -> use_cases/ -> entities/
  repos/ implements interfaces defined in use_cases/
  tools/ are standalone utilities"

# Output as JSON with additionalContext
jq -n --arg ctx "$CONTEXT" '{
    "hookSpecificOutput": {
        "additionalContext": $ctx
    }
}'
