# Slice discipline

Read at [Step 4](PLANNING.md#step-4--plan-cut-into-slices) and in [Step 5.5](IMPLEMENTATION.md#55-plan-write-the-slices-tests-then-implement-one-test-at-a-time); *placeholder*, *seam* and *tier* are defined in [Terms](SKILL.md#terms). It covers slice ownership, dependencies, placeholders, ordering and size.

## Iterative and incremental, without exception

**Nothing is built unless it is part of the current slice.** A slice delivers one path of behaviour end to end. Everything that path needs but the slice does not own is either:

- **reused as it already exists**, or
- **reached through a contract and satisfied by a placeholder**.

## Existing dependencies come first

When what the slice needs already exists and works, use it through its existing interface. Wrapping it in a new contract or a placeholder violates Surgical Changes. If it has no seam the scenarios can reach, that is a design question for Step 3.

## Contracts and placeholders

These rules apply to dependencies that are **not available**: not built yet, deferred to a later slice, or in a system not yet integrated.

- **Contract:** declare the **real contract** (a repository or port interface), shaped by the consumer's needs. It lives in the domain layer when there is one.
- **Placeholder:** satisfy the contract with the simplest **placeholder adapter** that runs the slice end to end, progressing hardcoded → in-memory or fixture → real adapter. Placeholders live in infrastructure or test support, never in the domain.
- **Acceptance tests** run against the contract, so they survive every replacement.
- **Contract test suite:** every contract gets one. It is written whole in 5.5, immediately before the contract and its placeholder, because it specifies an interface.
  - Every implementation passes it, the placeholder included.
  - A real adapter passes it before the placeholder is deleted.
- **Registration:** register each placeholder under the introducing slice's `placeholders.introduces`, with name, what it stands in for, location, security and `replacedBy`. A placeholder without `replacedBy` is a finding.
- **Replacement:** the slice that brings the real adapter **deletes the placeholder** and lists it in its `placeholders.replaces`. A placeholder never stays beside its replacement.
- **Security placeholders** (identity, roles, permissions, tenancy) are marked as such.
  - A **deployable build** is anything leaving development: staging, demo, pilot or production.
  - A deployable build holds a security placeholder only under a recorded user decision, and only with test data.
  - With real data, it is a hard constraint that no decision lifts.
- **Security model:** contracts carry it from the first slice. Every use case receives the acting principal.

Only a slice whose scope says so refines or replaces a placeholder.

## Slice ordering

Recommend this order of tiers, and say why when departing from it:

1. **Business rules and functionality**: the behaviour the domain exists for.
2. **Security**: identity, authentication, authorisation, session and tenancy enforcement, auditing. A rule the business states on its own ("a customer sees only their invoices") belongs to tier 1.
3. **Infrastructure**: real persistence, messaging, external integrations, deployment, observability.

Within a tier, order by dependency, then by risk: the slice most likely to change the design goes first.

In any tier:

- An unknown that could invalidate the plan may justify a time-boxed **investigation slice**. It produces a decision, a contract or a measured fact.
- Governing context can pull a slice forward.

The user decides the default priority and the binding constraints.

- Record the recommendation, reasons and decision in one register note.
- Table order carries the priority.
- Binding constraints go in `dependsOn` ([Z1](REGISTER-SCHEMA.md#rules-z1z7)).

## Lane, size and splitting

- **Lane:** at Step 4, classify each slice **local** or **transversal** ([Risk lanes](SKILL.md#risk-lanes)) and record it in the spec. In a `lite` project the lane is **lite**.
- **Splitting:** in 5.4, split the slice by domain before approval when the impact map shows several domains, or an envelope much larger than the behaviour it delivers.
- **Size ceiling:** record the slice's size ceiling in its spec. Above a threshold the project sets, a written justification is required.
- A mechanical mass change without behaviour belongs to the R lane ([Behaviour-free refactor](SHORT-PATHS.md#behaviour-free-refactor-r-lane)), not to a slice.
