# Slice discipline

Read at [PLANNING.md](PLANNING.md) Step 4 and in Step 5.5: slice ownership, dependencies, placeholders, ordering and size.

## Iterative and incremental, without exception

**Nothing is built unless it is part of the current slice.** A slice delivers one path of behaviour end to end; everything that path needs but the slice does not own is either **reused as it already exists** or **reached through a contract and satisfied by a placeholder**.

## Existing dependencies come first

When what the slice needs already exists and works, use it through its existing interface. Wrapping it in a new contract or a placeholder is a Surgical Changes violation. If it has no seam the scenarios can reach, that is a design question for Step 3.

## Contracts and placeholders

For dependencies that are **not available** — not built yet, deferred to a later slice, or in a system not yet integrated:

- Declare the **real contract** (repository or port interface; in the domain layer when there is one), shaped by the consumer's needs.
- Satisfy it with the simplest **placeholder adapter** that runs the slice end to end (hardcoded → in-memory or fixture → real adapter). Placeholders live in infrastructure or test support, never in the domain.
- Acceptance tests run against the contract, so they survive every replacement.
- Every contract gets a **contract test suite**, written whole in 5.5 immediately before the contract and its placeholder, because it specifies an interface. Every implementation passes it, the placeholder included; a real adapter passes it before the placeholder is deleted.
- Register each placeholder under the introducing slice's `placeholders.introduces` (name, stands in for, location, security, `replacedBy`). A placeholder without `replacedBy` is a finding.
- The slice bringing the real adapter **deletes the placeholder** and lists it in its `placeholders.replaces`. No placeholder stays beside its replacement.
- Security placeholders (identity, roles, permissions, tenancy) are marked as such. A **deployable build** (anything leaving development: staging, demo, pilot, production) holds one only under a recorded user decision and only with test data; with real data it is a hard constraint no decision lifts.
- Contracts carry the security model from the first slice: every use case receives the acting principal.

Only a slice whose scope says so refines or replaces a placeholder.

## Slice ordering

Recommend this order and say why when departing from it:

1. **Business rules and functionality** — the behaviour the domain exists for.
2. **Security** — identity, authentication, authorisation, session and tenancy enforcement, auditing. A rule the business states on its own ("a customer sees only their invoices") is tier 1.
3. **Infrastructure** — real persistence, messaging, external integrations, deployment, observability.

Within a tier, order by dependency, then risk: the slice most likely to change the design goes first. An unknown that could invalidate the plan may justify a time-boxed **investigation slice** producing a decision, contract or measured fact. Governing context can pull a slice forward. The user decides the default priority and binding constraints; record recommendation, reasons and decision in one register note. Table order carries priority; binding constraints go in `dependsOn` (Z1).

## Lane, size and splitting

At Step 4, classify each slice **local** or **transversal** (**lite** in a `lite` project; SKILL.md *Risk lanes*) and record it in the spec. In 5.4, when the impact map shows several domains, or an envelope much larger than the behaviour it delivers, split the slice by domain before approval. Record the slice's size ceiling in its spec; above a threshold the project sets, a written justification is required. A mechanical mass change without behaviour belongs to the R lane (SHORT-PATHS), not to a slice.
