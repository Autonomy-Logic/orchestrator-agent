"""Architecture tests that enforce Clean Architecture dependency rules.

Uses Python's ast module to parse every .py file in src/, extract imports,
classify each import into an architectural layer, and assert that no
forbidden cross-layer dependencies exist.
"""

from __future__ import annotations

import ast
from pathlib import Path


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


def get_python_files(layer_dir: str) -> list[Path]:
    """Return all .py files under src/<layer_dir>/, recursively."""
    return sorted((SRC_ROOT / layer_dir).rglob("*.py"))


def extract_imports(filepath: Path) -> list[tuple[str, int]]:
    """Extract absolute import module names and line numbers from a file.

    Skips relative imports (level > 0) since those are always same-layer.
    Returns a list of (module_name, line_number) tuples.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                imports.append((node.module, node.lineno))
    return imports


def classify_import(module_name: str) -> str | None:
    """Classify an import into an architectural layer.

    Returns:
        "entities", "tools", "repos.interfaces", "repos", "use_cases",
        "controllers", "bootstrap", or None (stdlib/external).
    """
    parts = module_name.split(".")

    if parts[0] == "entities":
        return "entities"
    if parts[0] == "tools":
        return "tools"
    if parts[0] == "repos":
        if len(parts) >= 2 and parts[1] == "interfaces":
            return "repos.interfaces"
        return "repos"
    if parts[0] == "use_cases":
        return "use_cases"
    if parts[0] == "controllers":
        return "controllers"
    if parts[0] == "bootstrap":
        return "bootstrap"
    return None


def assert_no_forbidden_imports(
    layer_dir: str,
    forbidden_layers: list[str],
    rule: str,
    reason: str,
    fix: str,
) -> None:
    """Assert that no file in layer_dir imports from any forbidden layer.

    Collects all violations and produces a clear, actionable failure message.
    """
    violations = []
    for filepath in get_python_files(layer_dir):
        for module_name, lineno in extract_imports(filepath):
            layer = classify_import(module_name)
            if layer in forbidden_layers:
                rel_path = filepath.relative_to(SRC_ROOT.parent)
                violations.append(f"    {rel_path}:{lineno} → import {module_name}")

    if violations:
        violations_str = "\n".join(violations)
        msg = (
            f"\n\nDEPENDENCY RULE VIOLATION\n\n"
            f"  Rule: {rule}\n"
            f"  Reason: {reason}\n\n"
            f"  Violations found:\n{violations_str}\n\n"
            f"  How to fix: {fix}\n"
        )
        raise AssertionError(msg)


class TestEntitiesHaveNoDependencies:
    """Entities (innermost layer) must only import from stdlib/typing."""

    def test_no_tools_imports(self):
        assert_no_forbidden_imports(
            layer_dir="entities",
            forbidden_layers=["tools"],
            rule="entities/ must not import from tools/",
            reason=(
                "Entities are the innermost layer with zero dependencies. "
                "They contain pure domain logic and must not depend on "
                "infrastructure utilities."
            ),
            fix=(
                "Move the dependency out of the entity. If the entity needs "
                "external behavior, define it as a method parameter or use "
                "dependency injection in the use case layer."
            ),
        )

    def test_no_repos_imports(self):
        assert_no_forbidden_imports(
            layer_dir="entities",
            forbidden_layers=["repos", "repos.interfaces"],
            rule="entities/ must not import from repos/",
            reason=(
                "Entities are the innermost layer with zero dependencies. "
                "They must not depend on data persistence adapters or their "
                "interfaces."
            ),
            fix=(
                "Remove the repository dependency from the entity. Entities "
                "should be pure domain objects that are persisted by repos, "
                "not aware of them."
            ),
        )

    def test_no_use_cases_imports(self):
        assert_no_forbidden_imports(
            layer_dir="entities",
            forbidden_layers=["use_cases"],
            rule="entities/ must not import from use_cases/",
            reason=(
                "Entities are the innermost layer with zero dependencies. "
                "They must not depend on application-specific orchestration "
                "logic."
            ),
            fix=(
                "Remove the use case dependency from the entity. Entities "
                "define business rules; use cases orchestrate them."
            ),
        )

    def test_no_controllers_imports(self):
        assert_no_forbidden_imports(
            layer_dir="entities",
            forbidden_layers=["controllers"],
            rule="entities/ must not import from controllers/",
            reason=(
                "Entities are the innermost layer with zero dependencies. "
                "They must not depend on transport-layer code."
            ),
            fix=(
                "Remove the controller dependency from the entity. This is "
                "a severe layer violation — entities should never be aware "
                "of how they are delivered to the outside world."
            ),
        )

    def test_no_bootstrap_imports(self):
        assert_no_forbidden_imports(
            layer_dir="entities",
            forbidden_layers=["bootstrap"],
            rule="entities/ must not import from bootstrap",
            reason=(
                "Entities are the innermost layer with zero dependencies. "
                "They must not depend on the composition root."
            ),
            fix=(
                "Remove the bootstrap dependency from the entity. The "
                "composition root wires dependencies; entities should not "
                "be aware of it."
            ),
        )


class TestToolsDoNotDependOnAppLayers:
    """Tools are standalone infrastructure — no app layer dependencies."""

    def test_no_entities_imports(self):
        assert_no_forbidden_imports(
            layer_dir="tools",
            forbidden_layers=["entities"],
            rule="tools/ must not import from entities/",
            reason=(
                "Tools are standalone infrastructure utilities. They must "
                "not depend on domain entities, which belong to the "
                "application's business logic layer."
            ),
            fix=(
                "Remove the entity dependency from the tool. If the tool "
                "needs to work with domain data, accept it as a parameter "
                "using primitive types or define a local data structure."
            ),
        )

    def test_no_use_cases_imports(self):
        assert_no_forbidden_imports(
            layer_dir="tools",
            forbidden_layers=["use_cases"],
            rule="tools/ must not import from use_cases/",
            reason=(
                "Tools are standalone infrastructure utilities. They must "
                "not depend on application-specific business logic."
            ),
            fix=(
                "Remove the use case dependency from the tool. Tools should "
                "be general-purpose and reusable across different use cases."
            ),
        )

    def test_no_controllers_imports(self):
        assert_no_forbidden_imports(
            layer_dir="tools",
            forbidden_layers=["controllers"],
            rule="tools/ must not import from controllers/",
            reason=(
                "Tools are standalone infrastructure utilities. They must "
                "not depend on transport-layer code."
            ),
            fix=(
                "Remove the controller dependency from the tool. Tools "
                "should have no knowledge of delivery mechanisms."
            ),
        )

    def test_no_bootstrap_imports(self):
        assert_no_forbidden_imports(
            layer_dir="tools",
            forbidden_layers=["bootstrap"],
            rule="tools/ must not import from bootstrap",
            reason=(
                "Tools are standalone infrastructure utilities. They must "
                "not depend on the composition root."
            ),
            fix=(
                "Remove the bootstrap dependency from the tool. If the tool "
                "needs configuration, accept it as a constructor parameter."
            ),
        )

    def test_no_repos_implementation_imports(self):
        assert_no_forbidden_imports(
            layer_dir="tools",
            forbidden_layers=["repos"],
            rule="tools/ must not import from repos/ (implementations)",
            reason=(
                "Tools are standalone infrastructure utilities. They must "
                "not depend on repository implementations. Importing from "
                "repos.interfaces (Protocol types) is allowed for type "
                "annotations."
            ),
            fix=(
                "Replace the concrete repo import with its interface from "
                "repos.interfaces, or accept the dependency as a parameter."
            ),
        )


class TestRepoInterfacesArePureProtocols:
    """Repo interfaces must be pure Protocol definitions — no implementation dependencies."""

    def test_no_tools_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos/interfaces",
            forbidden_layers=["tools"],
            rule="repos/interfaces/ must not import from tools/",
            reason=(
                "Repository interfaces are pure Protocol definitions that "
                "define contracts. They must not depend on infrastructure "
                "utilities."
            ),
            fix=(
                "Remove the tools dependency from the interface. Interfaces "
                "should use only stdlib types (str, int, dict, etc.) and "
                "domain entities in their signatures."
            ),
        )

    def test_no_repo_implementation_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos/interfaces",
            forbidden_layers=["repos"],
            rule="repos/interfaces/ must not import from repos/ (implementations)",
            reason=(
                "Repository interfaces define contracts that implementations "
                "fulfill. They must not depend on their own implementations."
            ),
            fix=(
                "Remove the concrete repo import from the interface. "
                "Interfaces define the contract; implementations depend on "
                "the interface, not the other way around."
            ),
        )

    def test_no_entities_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos/interfaces",
            forbidden_layers=["entities"],
            rule="repos/interfaces/ must not import from entities/",
            reason=(
                "Repository interfaces are pure Protocol definitions. "
                "They should use primitive types in their signatures rather "
                "than coupling to domain entities."
            ),
            fix=(
                "Replace entity types in the interface signature with "
                "primitive types or define the needed types locally."
            ),
        )

    def test_no_use_cases_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos/interfaces",
            forbidden_layers=["use_cases"],
            rule="repos/interfaces/ must not import from use_cases/",
            reason=(
                "Repository interfaces are pure Protocol definitions. "
                "They must not depend on application-specific business "
                "logic."
            ),
            fix=(
                "Remove the use case dependency from the interface. "
                "Repository interfaces should only define data access "
                "contracts."
            ),
        )

    def test_no_controllers_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos/interfaces",
            forbidden_layers=["controllers"],
            rule="repos/interfaces/ must not import from controllers/",
            reason=(
                "Repository interfaces are pure Protocol definitions. "
                "They must not depend on transport-layer code."
            ),
            fix=(
                "Remove the controller dependency from the interface. "
                "This is a severe layer violation."
            ),
        )

    def test_no_bootstrap_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos/interfaces",
            forbidden_layers=["bootstrap"],
            rule="repos/interfaces/ must not import from bootstrap",
            reason=(
                "Repository interfaces are pure Protocol definitions. "
                "They must not depend on the composition root."
            ),
            fix=(
                "Remove the bootstrap dependency from the interface."
            ),
        )


class TestReposDoNotDependOnBusinessLogic:
    """Repos (adapters) must not import use_cases or controllers."""

    def test_no_use_cases_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos",
            forbidden_layers=["use_cases"],
            rule="repos/ must not import from use_cases/",
            reason=(
                "Repositories are data persistence adapters. They must not "
                "depend on application-specific business logic. Data flows "
                "from use cases to repos, not the other way around."
            ),
            fix=(
                "Remove the use case dependency from the repository. If "
                "the repo needs business logic, it should be pushed down "
                "from the use case layer via method parameters."
            ),
        )

    def test_no_controllers_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos",
            forbidden_layers=["controllers"],
            rule="repos/ must not import from controllers/",
            reason=(
                "Repositories are data persistence adapters. They must not "
                "depend on transport-layer code. Controllers call use cases, "
                "which call repos — never the reverse."
            ),
            fix=(
                "Remove the controller dependency from the repository. "
                "Repos should be unaware of how the application is delivered."
            ),
        )

    def test_no_bootstrap_imports(self):
        assert_no_forbidden_imports(
            layer_dir="repos",
            forbidden_layers=["bootstrap"],
            rule="repos/ must not import from bootstrap",
            reason=(
                "Repositories are data persistence adapters. They must not "
                "depend on the composition root. The composition root wires "
                "repos into use cases, not the other way around."
            ),
            fix=(
                "Remove the bootstrap dependency from the repository. If "
                "the repo needs configuration, accept it as a constructor "
                "parameter injected by the composition root."
            ),
        )


class TestUseCasesDoNotDependOnOuterLayers:
    """Use cases must not import repo implementations, controllers, or bootstrap."""

    def test_no_repo_implementation_imports(self):
        assert_no_forbidden_imports(
            layer_dir="use_cases",
            forbidden_layers=["repos"],
            rule="use_cases/ must not import from repos/ (implementations)",
            reason=(
                "Use cases define application business logic. They depend "
                "on repository interfaces (defined as Protocols), not "
                "concrete implementations. This is the Dependency Inversion "
                "Principle — use cases own the interface, repos implement it."
            ),
            fix=(
                "Replace the concrete repo import with its Protocol "
                "interface from repos.interfaces. Accept the repo as a "
                "parameter typed to the interface."
            ),
        )

    def test_no_controllers_imports(self):
        assert_no_forbidden_imports(
            layer_dir="use_cases",
            forbidden_layers=["controllers"],
            rule="use_cases/ must not import from controllers/",
            reason=(
                "Use cases define application business logic. They must not "
                "depend on transport-layer code. Controllers call use cases, "
                "never the reverse."
            ),
            fix=(
                "Remove the controller dependency from the use case. If a "
                "use case needs to trigger a controller action, define a "
                "callback interface that the controller implements."
            ),
        )

    def test_no_bootstrap_imports(self):
        assert_no_forbidden_imports(
            layer_dir="use_cases",
            forbidden_layers=["bootstrap"],
            rule="use_cases/ must not import from bootstrap",
            reason=(
                "Use cases define application business logic. They must not "
                "depend on the composition root. Dependencies should be "
                "injected, not pulled from bootstrap."
            ),
            fix=(
                "Remove the bootstrap import and accept the dependency as "
                "a parameter. The composition root wires dependencies into "
                "use cases at startup."
            ),
        )


class TestControllersDoNotBypassUseCases:
    """Controllers must not reach into repos or entities directly."""

    def test_no_repos_imports(self):
        assert_no_forbidden_imports(
            layer_dir="controllers",
            forbidden_layers=["repos", "repos.interfaces"],
            rule="controllers/ must not import from repos/",
            reason=(
                "Controllers are transport-layer adapters. They must "
                "interact with data through use cases, not by reaching "
                "directly into repositories. This ensures all business "
                "logic runs through the use case layer."
            ),
            fix=(
                "Remove the repo dependency from the controller. Route "
                "the data access through a use case instead."
            ),
        )

    def test_no_entity_imports(self):
        assert_no_forbidden_imports(
            layer_dir="controllers",
            forbidden_layers=["entities"],
            rule="controllers/ must not import from entities/",
            reason=(
                "Controllers are transport-layer adapters. They should "
                "work with DTOs and plain dicts, not domain entities "
                "directly. Entity access should be mediated by use cases."
            ),
            fix=(
                "Remove the entity dependency from the controller. Pass "
                "data to use cases as plain dicts or DTOs, and let the "
                "use case layer work with entities."
            ),
        )


class TestBootstrapIsOnlyCompositionRoot:
    """Only index.py and controllers/ may import bootstrap."""

    def test_no_entity_imports_bootstrap(self):
        assert_no_forbidden_imports(
            layer_dir="entities",
            forbidden_layers=["bootstrap"],
            rule="entities/ must not import from bootstrap",
            reason=(
                "Bootstrap is the composition root. Only the entry point "
                "(index.py) and controllers should import from it."
            ),
            fix=(
                "Remove the bootstrap dependency from the entity."
            ),
        )

    def test_no_tools_imports_bootstrap(self):
        assert_no_forbidden_imports(
            layer_dir="tools",
            forbidden_layers=["bootstrap"],
            rule="tools/ must not import from bootstrap",
            reason=(
                "Bootstrap is the composition root. Tools are standalone "
                "utilities and must not depend on application wiring."
            ),
            fix=(
                "Remove the bootstrap dependency from the tool. Accept "
                "configuration as a parameter instead."
            ),
        )

    def test_no_repos_imports_bootstrap(self):
        assert_no_forbidden_imports(
            layer_dir="repos",
            forbidden_layers=["bootstrap"],
            rule="repos/ must not import from bootstrap",
            reason=(
                "Bootstrap is the composition root. Repos must not depend "
                "on application wiring."
            ),
            fix=(
                "Remove the bootstrap dependency from the repo. Accept "
                "dependencies as constructor parameters."
            ),
        )

    def test_no_use_cases_imports_bootstrap(self):
        assert_no_forbidden_imports(
            layer_dir="use_cases",
            forbidden_layers=["bootstrap"],
            rule="use_cases/ must not import from bootstrap",
            reason=(
                "Bootstrap is the composition root. Use cases must receive "
                "their dependencies via injection, not by pulling from "
                "the composition root."
            ),
            fix=(
                "Remove the bootstrap import and accept the dependency as "
                "a parameter injected by the composition root."
            ),
        )
