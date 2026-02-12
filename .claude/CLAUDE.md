# Clean Architecture Reference Guide

This document provides comprehensive clean architecture knowledge for use when working on this codebase.

## Origins and Core Philosophy

Clean Architecture was formalized by Robert C. Martin (Uncle Bob) in his 2017 book *Clean Architecture: A Craftsman's Guide to Software Structure and Design*. It synthesizes earlier ideas: Hexagonal Architecture (Cockburn, 2005), Onion Architecture (Palermo, 2008), and BCE (Jacobson, 1992).

**Central thesis:** Business logic is the most important part of a software system and must be independent of frameworks, databases, UI, delivery mechanisms, and third-party services. The application owns the framework, not the other way around.

---

## The Dependency Rule

> Source code dependencies must point only inward, toward higher-level policies.

This is the single most important rule. Inner layers must never import, reference, or have knowledge of outer layers. Outer layers may reference inner layers.

```
WRONG: use_cases/create_order.py imports from flask    (inner depends on outer)
RIGHT: controllers/order_ctrl.py imports from use_cases (outer depends on inner)
```

When an inner layer needs to invoke something in an outer layer (e.g., save to database), use the **Dependency Inversion Principle**: the inner layer defines an interface, the outer layer implements it, and the composition root wires them together at runtime.

---

## The Concentric Layers

```
+--------------------------------------------------+
|                Frameworks & Drivers               |
|   +------------------------------------------+   |
|   |           Interface Adapters             |   |
|   |   +----------------------------------+   |   |
|   |   |          Use Cases               |   |   |
|   |   |   +--------------------------+   |   |   |
|   |   |   |        Entities          |   |   |   |
|   |   |   +--------------------------+   |   |   |
|   |   +----------------------------------+   |   |
|   +------------------------------------------+   |
+--------------------------------------------------+

Dependencies point INWARD -->
```

### Entities (Enterprise Business Rules) — Innermost

- Core domain objects with behavior, not just data containers
- Enforce business invariants (e.g., "order must have at least one item")
- No dependencies on any other layer — pure business logic
- Include: domain objects, value objects, domain events, enterprise validation
- NOT database models, ORM objects, or framework data classes

```python
class Order:
    def __init__(self, customer_id: str, items: list[OrderItem]):
        if not items:
            raise InvalidOrderError("Order must have at least one item")
        self.customer_id = customer_id
        self.items = items
        self.status = OrderStatus.PENDING

    def confirm(self) -> None:
        if self.status != OrderStatus.PENDING:
            raise BusinessRuleViolation("Only pending orders can be confirmed")
        self.status = OrderStatus.CONFIRMED
```

### Use Cases (Application Business Rules) — Second Circle

- Application-specific orchestration logic
- Coordinate entities and define input/output port interfaces
- Each use case = one specific application action
- Define repository/gateway interfaces (output ports) that outer layers implement

```python
class OrderRepository(ABC):
    @abstractmethod
    def save(self, order: Order) -> None: ...

class CreateOrderUseCase:
    def __init__(self, order_repo: OrderRepository, payment: PaymentGateway):
        self.order_repo = order_repo
        self.payment = payment

    def execute(self, request: CreateOrderRequest) -> CreateOrderResponse:
        order = Order(customer_id=request.customer_id, items=...)
        self.payment.charge(order.customer_id, order.total)
        order.confirm()
        self.order_repo.save(order)
        return CreateOrderResponse(order_id=order.id, status=order.status.value)
```

**Key distinction:** Entities = "an order must have items" (enterprise truth). Use Cases = "charge payment, then confirm, then save" (application workflow).

### Interface Adapters (Controllers, Gateways, Presenters) — Third Circle

- Convert data between use case format and external format
- **Controllers** (primary/driving adapters): receive external input, call use cases
- **Repositories** (secondary/driven adapters): implement output port interfaces with actual DB/Docker/API code
- ORM models live here, not in entities. Repository maps between ORM model and domain entity.

### Frameworks & Drivers — Outermost

- Web framework config, DB connections, message queue setup, the `main()` entry point
- Most volatile code, mostly configuration and wiring
- The **composition root** lives here

---

## Key Principles

### Dependency Inversion Principle (DIP)

The mechanism that makes Clean Architecture work. High-level modules (use cases, entities) define interfaces. Low-level modules (databases, frameworks) implement them.

```
WITHOUT DIP:  UseCase --> PostgresRepository --> Database     (rule violated)
WITH DIP:     UseCase --> OrderRepository (interface)          (rule preserved)
                               ^
              PostgresRepository (implements, lives in outer layer)
```

### Interface Segregation

Use cases define narrow, focused interfaces. Prefer `OrderReader` + `OrderWriter` over one monolithic `DataAccessLayer`.

### Screaming Architecture

The directory structure should reveal what the system does, not what framework it uses. Top-level folders should be domain concepts, not technical layers.

### Single Responsibility at Architecture Level

- Entities change only when business rules change
- Use cases change only when application behavior changes
- Adapters change only when external data formats change
- Frameworks change only when you swap tools

---

## Ports and Adapters (Hexagonal Architecture)

Clean Architecture is heavily influenced by Hexagonal Architecture. The mapping:

| Hexagonal | Clean Architecture |
|---|---|
| Application Core | Entities + Use Cases |
| Input Port | Use Case interface (`execute` method) |
| Output Port | Repository/Gateway interface (defined in use case layer) |
| Primary/Driving Adapter | Controller (Interface Adapter layer) |
| Secondary/Driven Adapter | Repository implementation (Interface Adapter layer) |

**Input Ports** = what the application can do (use case interfaces, called by external actors)
**Output Ports** = what the application needs (repository/gateway interfaces, implemented by infrastructure)

---

## Data Flow and Boundary Crossing

Data crosses boundaries via simple DTOs (data transfer objects), not entities.

```
HTTP JSON <--controller--> Request DTO <--use case--> Entity <--repository--> DB Model
```

**Why not pass entities across boundaries?**
- Entities contain business behavior outer layers shouldn't access
- Entity internal changes would ripple outward
- Information hiding — outer layers may need less data

Each boundary has its own data structures. Mapping between them is the "tax" for decoupling.

---

## Repository Pattern

- Interface defined in use case layer (output port)
- Implementation lives in adapter/infrastructure layer
- Returns domain entities, not DB rows or ORM objects
- Collection-like API: `find_by_id`, `save`, `delete`, `list_all`
- No query language leakage (no SQL in use cases)
- One repository per aggregate root

---

## Composition Root / Dependency Injection

The single place where all concrete implementations are instantiated and wired together. Lives at the outermost layer, as close to the entry point as possible.

```python
def build_application():
    # Infrastructure
    docker_client = docker.from_env()

    # Repositories (adapters implementing use case ports)
    runtime_repo = DockerRuntimeRepository(docker_client)

    # Use cases (wired with dependencies)
    create_runtime = CreateRuntimeUseCase(runtime_repo)

    # Controllers (wired with use cases)
    controller = RuntimeController(create_runtime)
    return controller
```

**Constructor injection** is preferred: dependencies passed through `__init__`, making them explicit and visible.

---

## Testing Benefits

The primary practical payoff. Each layer is independently testable:

- **Entities**: Pure logic, no mocks needed, no setup
- **Use Cases**: Inject test doubles (in-memory repos, stub gateways, spy notifiers)
- **Adapters**: Mock use cases for controller tests; integration tests for repository implementations
- **Testing pyramid**: Many fast unit tests (entities + use cases), fewer integration tests (adapters), few E2E tests (wiring)

---

## Common Mistakes

1. **Framework leakage**: Importing Flask/SQLAlchemy in use cases. Fix: use DTOs and repository interfaces.
2. **Anemic use cases**: Pass-through to repository with no logic. Acceptable for simple CRUD if the boundary is intentional; anti-pattern if all use cases are this thin.
3. **Over-engineering**: Full 4-layer architecture for simple CRUD. Match architecture to complexity.
4. **Entities without behavior**: Data-only classes with no business rule enforcement. Entities should protect invariants.
5. **Skipping layers**: Controllers directly accessing the database. Violates dependency rule.
6. **Shared DTOs across boundaries**: Using the same class for HTTP body, use case input, and DB model. Couples all layers together.

---

## When to Apply

**Use Clean Architecture when:**
- Significant, evolving business logic
- Multiple delivery mechanisms (web, CLI, message queue)
- Long-lived system maintained by a team
- Need to test business logic independently
- Data store or framework may change

**Use simpler patterns when:**
- Primarily CRUD with little business logic
- Short-lived prototype
- Small team, simple domain
- Time-to-market is primary constraint

**Pragmatic approach:** Start simple, refactor toward clean boundaries as complexity grows. Clean Architecture is guidelines, not commandments. The goal is maintainable, testable software — not architectural purity for its own sake.

---

## Folder Organization Options

**Layered (by technical concern):**
```
src/
    entities/
    use_cases/
        ports/           # output port interfaces
    adapters/
        controllers/     # primary/driving
        repositories/    # secondary/driven
    infrastructure/      # frameworks & drivers
    main.py              # composition root
```

**Feature-based (Screaming Architecture):**
```
src/
    orders/
        entity.py, create_order.py, repository.py, postgres_repository.py, controller.py
    runtimes/
        entity.py, create_runtime.py, repository.py, docker_repository.py, controller.py
```

**Hybrid (common in practice):**
```
src/
    domain/              # entities
    use_cases/           # use cases + ports
    adapters/
        inbound/         # controllers
        outbound/        # repositories, gateways
    config/              # composition root
    main.py
```

## Cross-Cutting Concerns

- **Logging**: Decorator pattern around repositories/use cases, or standard logging (considered a language feature)
- **Authentication**: Outermost layer middleware
- **Authorization**: May be a use case concern if rules are business-specific
- **Error handling**: Inner layers raise domain exceptions; outer layers translate to transport responses (HTTP 404, 422, etc.)
