#!/usr/bin/env bash
set -euo pipefail

USAGE="Usage: $(basename "$0") [-u|--unit] [-a|--architecture] [-c|--coverage]

Run the orchestrator-agent test suite.

Options:
  -u, --unit           Run only unit tests
  -a, --architecture   Run only architecture tests
  -c, --coverage       Run with coverage report and assert 100% on mandatory modules
                       (cannot be combined with --architecture)

If no options are provided, both unit and architecture tests are run.
"

run_unit=false
run_arch=false
coverage=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        -u|--unit)
            run_unit=true
            shift
            ;;
        -a|--architecture)
            run_arch=true
            shift
            ;;
        -c|--coverage)
            coverage=true
            shift
            ;;
        -h|--help)
            echo "$USAGE"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "$USAGE" >&2
            exit 1
            ;;
    esac
done

# Default: run both if neither specified
if ! $run_unit && ! $run_arch; then
    run_unit=true
    run_arch=true
fi

# Validate: --coverage cannot be combined with --architecture only
if $coverage && $run_arch && ! $run_unit; then
    echo "Error: --coverage cannot be combined with --architecture alone." >&2
    echo "Coverage measures unit tests. Use --coverage with --unit or without flags." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

PYTEST_ARGS=(-v --tb=short)
TARGETS=()

if $run_unit; then
    TARGETS+=(tests/unit/)
fi

if $run_arch; then
    TARGETS+=(tests/architecture/)
fi

if $coverage; then
    PYTEST_ARGS+=(
        --cov=src/entities
        --cov=src/tools
        --cov=src/use_cases
        --cov-report=term-missing
        --cov-fail-under=100
    )
fi

cd "$REPO_ROOT"
python3 -m pytest "${TARGETS[@]}" "${PYTEST_ARGS[@]}"
