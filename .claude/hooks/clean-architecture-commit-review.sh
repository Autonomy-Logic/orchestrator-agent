#!/usr/bin/env bash
# Clean Architecture Commit Review Hook
# Runs before Bash tool calls. If the command is a git commit, gathers
# the staged diff, scans for dependency rule violations, and injects
# findings so Claude reviews before proceeding.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Only intercept git commit commands
case "$COMMAND" in
    *git\ commit*|*git\ -C\ *commit*) ;;
    *) exit 0 ;;
esac

CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
if [ -z "$CWD" ]; then
    CWD="$CLAUDE_PROJECT_DIR"
fi

# Get the staged diff (only src/ files)
DIFF=$(git -C "$CWD" diff --cached --name-only -- 'src/' 2>/dev/null || true)

if [ -z "$DIFF" ]; then
    exit 0
fi

# Scan staged source files for import violations
VIOLATIONS=""

while IFS= read -r file; do
    FULL_PATH="$CWD/$file"
    [ -f "$FULL_PATH" ] || continue

    # Determine which layer this file belongs to
    LAYER=""
    case "$file" in
        src/entities/*)    LAYER="entities" ;;
        src/use_cases/*)   LAYER="use_cases" ;;
        src/controllers/*) LAYER="controllers" ;;
        src/repos/*)       LAYER="repos" ;;
        src/tools/*)       LAYER="tools" ;;
        *) continue ;;
    esac

    # Check for forbidden imports based on layer
    case "$LAYER" in
        entities)
            # Entities must not import from any other layer
            BAD=$(grep -nE '^\s*(from|import)\s+(use_cases|controllers|repos|tools)\b' "$FULL_PATH" 2>/dev/null || true)
            if [ -n "$BAD" ]; then
                VIOLATIONS="$VIOLATIONS\n  VIOLATION in $file (entities layer imports outer layer):\n$BAD"
            fi
            ;;
        use_cases)
            # Use cases must not import from controllers or repos implementations
            BAD=$(grep -nE '^\s*(from|import)\s+(controllers)\b' "$FULL_PATH" 2>/dev/null || true)
            if [ -n "$BAD" ]; then
                VIOLATIONS="$VIOLATIONS\n  VIOLATION in $file (use_cases layer imports controllers):\n$BAD"
            fi
            ;;
        repos)
            # Repos must not import from use_cases or controllers
            BAD=$(grep -nE '^\s*(from|import)\s+(use_cases|controllers)\b' "$FULL_PATH" 2>/dev/null || true)
            if [ -n "$BAD" ]; then
                VIOLATIONS="$VIOLATIONS\n  VIOLATION in $file (repos layer imports inward/lateral):\n$BAD"
            fi
            ;;
        tools)
            # Tools must not import from use_cases or controllers
            BAD=$(grep -nE '^\s*(from|import)\s+(use_cases|controllers)\b' "$FULL_PATH" 2>/dev/null || true)
            if [ -n "$BAD" ]; then
                VIOLATIONS="$VIOLATIONS\n  VIOLATION in $file (tools layer imports use_cases/controllers):\n$BAD"
            fi
            ;;
    esac
done <<< "$DIFF"

# Build the review context
STAGED_DIFF=$(git -C "$CWD" diff --cached -- 'src/' 2>/dev/null || true)

if [ -n "$VIOLATIONS" ]; then
    REVIEW="CLEAN ARCHITECTURE COMMIT REVIEW — VIOLATIONS DETECTED

The following dependency rule violations were found in staged files:
$(echo -e "$VIOLATIONS")

DO NOT proceed with this commit. Fix the violations first.
The dependency rule requires: controllers/ -> use_cases/ -> entities/
repos/ implements interfaces defined in use_cases/. tools/ are standalone.

Staged diff for reference:
$STAGED_DIFF"

    # Exit code 2 blocks the tool call and feeds stderr to Claude
    echo "$REVIEW" >&2
    exit 2
else
    REVIEW="CLEAN ARCHITECTURE COMMIT REVIEW — No import violations detected in staged files.

Review the staged changes below and confirm they follow clean architecture principles:
- Dependencies point inward only (controllers -> use_cases -> entities)
- Use cases inject dependencies via parameters, not direct imports
- Controllers contain no business logic
- Repos implement use case interfaces

Staged src/ files: $(echo "$DIFF" | tr '\n' ', ')

Staged diff:
$STAGED_DIFF"

    jq -n --arg ctx "$REVIEW" '{
        "hookSpecificOutput": {
            "additionalContext": $ctx
        }
    }'
fi
