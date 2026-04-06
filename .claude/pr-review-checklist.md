# PR Review Checklist

## Clean Architecture

- [ ] **Dependency rule respected** — source dependencies point inward only (entities -> use_cases -> controllers/repos/tools). No inner layer imports from outer layers.
- [ ] **Correct layer placement** — new code lives in the right layer:
  - Domain entities, value objects, domain errors -> `entities/`
  - Business logic, use case orchestration, output port interfaces -> `use_cases/`
  - Transport handling (WebSocket/WebRTC topic routing, message parsing) -> `controllers/`
  - Data persistence adapters (Docker API, JSON files, Socket.IO clients) -> `repos/`
  - Infrastructure utilities (logging, protocol helpers, validation) -> `tools/`
  - Dependency wiring -> `bootstrap.py`
- [ ] **Port/adapter pattern** — repository and gateway interfaces defined or implied by use cases; implementations in `repos/`. Use cases never import concrete repository implementations.
- [ ] **Composition root respected** — all dependency wiring happens in `bootstrap.py`, not scattered across modules.
- [ ] **Entities encapsulate invariants** — business rules live in domain entities, not in use cases or controllers.
- [ ] **Controllers delegate to use cases** — no business logic in topic handlers or WebRTC signal handlers. Controllers parse messages, call use cases, format responses.
- [ ] **One use case per intent** — no monolithic service classes. Each use case has a single entry point.

## Python Conventions

- [ ] **Topic handler pattern followed** — new topics use the `@topic` / `@validate_message` / `@with_response` decorator chain. Handlers return plain dicts; decorators handle `action` and `correlation_id`.
- [ ] **Contract validation used** — message schemas defined with `StringType`, `NonEmptyStringType`, `NumberType`, etc. from `tools/contract_validation.py`. No ad-hoc validation in handlers.
- [ ] **Operations state checked** — container lifecycle operations (create, delete, update) use `begin_operation` / `clear_state` to prevent race conditions.
- [ ] **Error handling at boundaries** — domain errors caught in controllers and translated to response dicts, not leaked as raw exceptions through WebSocket.
- [ ] **No direct Docker/infrastructure access in use cases** — persistence and infrastructure go through repository interfaces or injected dependencies.

## Python & Code Quality

- [ ] **Type hints present** — function signatures include type annotations. No bare `dict` or `list` where a typed structure is appropriate.
- [ ] **No over-engineering** — no premature abstractions, unnecessary helpers, feature flags, or backwards-compat shims.
- [ ] **No unnecessary additions** — no docstrings/comments/type annotations on unchanged code. Comments only where logic isn't self-evident.
- [ ] **No dead code** — unused imports, variables, or commented-out code removed.
- [ ] **PEP 8 compliance** — snake_case functions and variables, 4-space indentation, consistent formatting.

## Security

- [ ] **OWASP top 10** — no command injection, path traversal, or other common vulnerabilities.
- [ ] **No secrets committed** — no `.env` files, credentials, API keys, certificates, or tokens.
- [ ] **mTLS boundaries enforced** — cloud communication uses mutual TLS. No unauthenticated endpoints exposed.

## Code Improvements & Refactoring Opportunities

> **Note:** Items in this section must be checked against the entire codebase, not just the files changed in the PR. New code may introduce duplication or inconsistencies with existing code elsewhere.

### Paradigm Consistency

- [ ] **Consistent programming paradigm** — all code follows the same style (functional use cases with injected dependencies, decorator-based topic handlers). No mixing without justification.
- [ ] **Consistent error handling pattern** — errors handled the same way across the codebase. No ad-hoc patterns.
- [ ] **Consistent async patterns** — async/await used uniformly. No mixing of raw coroutines, callbacks, and async/await for the same kind of operation.

### Duplication & Reuse

- [ ] **No duplicated logic** — repeated code blocks (3+ lines appearing in 2+ places) extracted into shared utilities or helpers.
- [ ] **No duplicated types** — identical or near-identical data structures consolidated into shared definitions.
- [ ] **No duplicated validation** — same validation rules appearing in multiple places extracted into reusable schemas or validators.

### Extraction Candidates

- [ ] **Shared helpers identified** — common Docker operations, network operations, or container patterns extracted (e.g., `stop_and_remove_container`, `remove_internal_network`).
- [ ] **Utility functions identified** — repeated transformations extracted into pure utility functions in `tools/`.

### Pattern Consistency

- [ ] **Naming conventions uniform** — handlers, variables, and file names follow consistent patterns across the codebase.
- [ ] **Consistent file structure** — files of the same type follow the same internal layout (imports -> constants -> implementation -> exports).

## General PR Hygiene

- [ ] **Scope** — changes match the PR description; no unrelated refactors or drive-by cleanups.
- [ ] **No file bloat** — existing files edited over new files created, unless new files are necessary.
- [ ] **Commit history** — clean, logical commits with meaningful messages focused on "why" not "what".
- [ ] **Tests** — use cases tested with in-memory repositories or mocks; architecture dependency tests pass.
