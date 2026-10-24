# Architecture recommendation: Domain-Driven Design

This is a recommendation, not a rule of the Zafir process; process vocabulary is in [Terms](SKILL.md#terms).

- **When it is offered:** once, in [Step 3.1](PLANNING.md#31-project-architecture-docsspecsarchitecturemd), with the reasons it fits the project or does not.
- **The choice:** the user chooses this style, another style, or none. All three are valid outcomes; choosing none is not a finding.
- **Recording:** whatever is chosen goes at the top of `docs/specs/architecture.md` as `Architecture style: DDD-lite | DDD | <other> | none`. An adopted style is also a Decisions entry.
- **Effect:** from then on, Step 5.5 implements within the recorded style and Step 5.7 checks it.
- **Change:** the style changes only by an approved Decisions entry or an explicit user instruction, recorded the same way.

## Ports for every I/O operation

Whatever style is chosen, including none, recommend in 3.1 and prefer in 5.5 a **port** for every I/O operation: database, clock, network, filesystem, randomness and external services. Domain and application code depend on the port; adapters implement it at the seams in `architecture.md`, and tests use in-memory adapters that pass the same contract suite ([Contracts and placeholders](SLICE-DISCIPLINE.md#contracts-and-placeholders)). Under DDD, repositories are such ports.

## When it fits

- **Lite project** (`Profile: lite`; see [Profile and architecture style](SPEC-LAYOUT.md#profile-and-architecture-style)): usually not. A project that is mostly CRUD over a simple model has no domain logic for a domain layer to hold. The Four Principles, seams, contracts and acceptance tests already give it what it needs. Recommend `none`, unless the user sees rules the CRUD hides.
- **Any other project**: recommend **DDD-lite** by default.
- **Full DDD** instead of DDD-lite when at least one of these holds:
  - more than one bounded context or subdomain with its own language;
  - distinct teams or systems that must integrate;
  - invariants that span aggregates;
  - a legacy or external model the new one must be protected from.

## DDD-lite

- **One bounded context.** The ubiquitous language lives in `CONTEXT.md`, and code names match the glossary. A term missing from the glossary is resolved with the user before it is coded.
- **An isolated domain layer:** entities, value objects and aggregates, with each aggregate enforcing its own invariants. The domain imports no framework, persistence, HTTP or UI code.
- **Repositories** are declared as interfaces in the domain and implemented in infrastructure.
- **Application services** (use cases) orchestrate the domain. Controllers, handlers and CLIs stay thin.
- **Adapters:** persistence, HTTP, UI and external APIs are adapters at the seams recorded in `architecture.md`.
- **Domain events:** every state change that matters to the business is raised by its aggregate as a named, past-tense domain event. Side effects (notifications, projections, integrations, other aggregates) react to events instead of being called from inside the aggregate.
- **Event dispatcher:** the default is a synchronous in-memory dispatcher in the application layer, registered as a placeholder under [Contracts and placeholders](SLICE-DISCIPLINE.md#contracts-and-placeholders). Outbox, broker and asynchronous delivery are infrastructure-tier slices, never built in the first slice that raises an event.
- **No context map** is required.

## Full DDD

Everything in DDD-lite, plus:

- Bounded contexts are named explicitly, with `CONTEXT-MAP.md` at the root and one `CONTEXT.md` per context.
- The map states the relationship between contexts (shared kernel, customer/supplier, conformist, anti-corruption layer, published language), and the code implements it as stated.
- Aggregate boundaries are transaction boundaries.
- Cross-aggregate and cross-context effects go only through domain events. Events that cross a context boundary are translated at that boundary.

## What adoption means in Step 5

**While implementing (5.5):**

- Domain logic goes in the domain layer and nowhere else.
- Invariants are enforced inside their aggregate.
- State changes that matter to the business raise domain events, and side effects react to them.
- Infrastructure is reached only through the interfaces the domain declares.
- Under full DDD, nothing crosses a context boundary except through the relationship the context map states.
- When implementation reveals a term that is missing, fuzzy or contradicted by the code, resolve it with the user and record it in `CONTEXT.md` before coding it.

**In review (5.7)**, check that:

- no domain logic leaked into adapters, handlers or UI;
- no infrastructure leaked into the domain;
- side effects react to domain events instead of being called from inside aggregates;
- `CONTEXT.md` still matches the vocabulary the code uses.
