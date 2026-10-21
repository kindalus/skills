# Architecture recommendation: Domain-Driven Design

This is a recommendation, not a rule of the Zafir process. It is offered to the user once, in Step 3.1, with the reasons it fits the project or does not; the user chooses this style, another, or none — all three are valid outcomes, and choosing none is not a finding. Whatever is chosen is recorded at the top of `docs/specs/architecture.md` as `Architecture style: DDD-lite | DDD | <other> | none`; an adopted style is also a Decisions entry. From then on Step 5.5 implements within the recorded style and Step 5.7 checks it. The style changes only by an approved Decisions entry or an explicit user instruction, recorded the same way.

## When it fits

- **Lite project** (`Profile: lite`, see *Profile and architecture style* in `SPEC-LAYOUT.md`): usually not. A project that is mostly CRUD over a simple model has no domain logic for a domain layer to hold; the Four Principles, seams, contracts, and acceptance tests already give it what it needs. Recommend `none` unless the user sees rules the CRUD hides.
- **Any other project**: recommend **DDD-lite** by default.
- **Full DDD** instead of DDD-lite when at least one holds: more than one bounded context or subdomain with its own language; distinct teams or systems that must integrate; invariants that span aggregates; a legacy or external model the new one must be protected from.

## DDD-lite

- One bounded context. The ubiquitous language lives in `CONTEXT.md`; code names match the glossary, and a term missing from the glossary is resolved with the user before it is coded.
- A domain layer isolated from everything else: entities, value objects, and aggregates whose invariants are enforced inside the aggregate. No framework, persistence, HTTP, or UI imports in the domain.
- Repositories declared as interfaces in the domain, implemented in infrastructure.
- Application services (use cases) orchestrate the domain; controllers, handlers, and CLIs stay thin.
- Persistence, HTTP, UI, and external APIs are adapters at the seams recorded in `architecture.md`.
- Domain events: every state change that matters to the business is raised by its aggregate as a named, past-tense domain event; side effects (notifications, projections, integrations, other aggregates) react to events rather than being called from inside the aggregate.
- The default event dispatcher is a synchronous in-memory one in the application layer, registered as a placeholder under [SLICE-DISCIPLINE.md](SLICE-DISCIPLINE.md) *Contracts and placeholders*. Outbox, broker, and asynchronous delivery are tier-3 slices — never built in the first slice that raises an event.
- No context map required.

## Full DDD

Everything in DDD-lite, plus:

- Bounded contexts named explicitly, with `CONTEXT-MAP.md` at the root and one `CONTEXT.md` per context.
- The relationship between contexts stated in the map (shared kernel, customer/supplier, conformist, anti-corruption layer, published language) and implemented as such.
- Aggregate boundaries are transaction boundaries; cross-aggregate and cross-context effects go only through domain events, and events that cross a context boundary are translated at that boundary.

## What adoption means in Step 5

**While implementing (5.5):** domain logic goes in the domain layer and nowhere else; invariants are enforced inside their aggregate; state changes that matter to the business raise domain events and side effects react to them; infrastructure is reached only through the interfaces the domain declares. Under full DDD, nothing crosses a context boundary except through the relationship the context map states. When implementation reveals a term that is missing, fuzzy, or contradicted by the code, resolve it with the user and record it in `CONTEXT.md` before coding it.

**In review (5.7):** no domain logic leaked into adapters, handlers, or UI; no infrastructure leaked into the domain; side effects react to domain events instead of being called from inside aggregates; `CONTEXT.md` still matches the vocabulary the code uses.
