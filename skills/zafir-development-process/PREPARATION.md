# Preparation — Steps 5.1–5.4

Procedure under [SKILL.md](SKILL.md); words such as *seam*, *envelope* and *base* are defined in [Terms](SKILL.md#terms). Preparation takes a planned slice to an approved, executable spec, which is the phase-1 commit. It writes no tests and no code. It also defines the freshness check at admission.

## Proportionality

Depth follows the slice's lane. The table binds both ways: do everything the lane requires, and impose nothing it does not.

| Element | Lite | Local | Transversal or first of a chain |
| --- | --- | --- | --- |
| Impact map | — | short: callers of touched signatures, tests and fakes, guards, database objects of touched tables | full ([Impact map](#impact-map)) |
| Feasibility design | one line per scenario | per scenario | per scenario |
| Delivery package, when the implementer did not prepare the slice | — | items 1, 4, 5 | all items |
| Pre-mortem | — | — | independent reviewer |

R-lane work follows [Behaviour-free refactor](SHORT-PATHS.md#behaviour-free-refactor-r-lane). Bug fixes and trivial changes need none of this.

## Decision round

There is one decision round each at preparation, admission, execution and integration.

- Each question gives options, their consequences and a recommendation.
- Ask every open question whose prerequisites are already answered.
- Outside the round, interrupt the user only for what blocks work in progress.
- Mechanism decisions (how, not what) are explained and recorded, not asked. The user may reverse them.
- At the third occurrence of the same decision type, propose a class authorisation. Record it like a pre-authorised class.

## Just-in-time and freshness

**Just-in-time preparation.** A slice may depend, directly or transitively, on a slice in execution. Prepare it only when that dependency has completed phase 3 or is integrated, and prepare it on the then-current integration branch. Independent slices do not wait.

**Freshness check at admission.** An approved spec waiting for admission is not revalidated while it waits. At admission, diff the integration branch since the approval commit against the impact map and the envelope:

- no effect on behaviour, scenarios or contracts → record the check and start;
- the diff touches the map → update the map; no new approval is needed;
- the diff changes a scenario or contract → make **one** amendment through 5.4, with every consumer closed.

## 5.1 Pick or create the slice

1. Locate the slice's mini-spec in `docs/specs/<feature-slug>/slices/` and its register row.
2. Confirm its lane.
3. Behaviour outside every approved brainstorm returns to Step 1.
4. A new slice within an approved plan is created now, under [Step 4](PLANNING.md#step-4--plan-cut-into-slices)'s rules.

**Done when:** the slice is located and registered within approved scope, or work has returned to its missing gate. No commit.

## 5.2 Refine and stress-test the slice

**Entry:** before any test or code.

1. List what the brainstorm, architecture, design and earlier slices already settled. Do not ask it again.
2. Look up codebase facts yourself.
3. Ask the user only about product gaps, risk gaps and hard-to-reverse decisions, in the [decision round](#decision-round).
4. Check settled decisions against governing context. Write durable ones to the wiki, link them from the spec, and resolve the `governingContext` assessment.
5. An unsettled gap makes the row `spec blocked`, with the blocker in `qualifier` and `nextAction`.
6. With no gaps, record **no open decisions**.

**Done when:** the spec holds the refined understanding and every gap is settled or blocked. The artefacts go into phase 1.

## 5.3 Keep documentation in sync

This is a standing duty through Step 5, not a one-off step.

- Whenever a slice changes state, update its register row ([STATUS-REGISTER](STATUS-REGISTER.md#how-the-process-writes-the-register)) and its spec. Commit them in the phase that caused the change.
- An implemented spec is never rewritten to change scope. New behaviour becomes a future slice.
- A derived scenario within scope is not a scope change.

## 5.4 Agree the seams, then define the acceptance scenarios

1. **Impact map** at the lane's depth ([Proportionality](#proportionality)).
2. **Seams:** list the public interfaces where behaviour is observed, each with its reason.
   - Ask the user only about a seam that is new, public-facing, crosses a module or context boundary, or is uncertain.
   - Reuse tested seams without asking.
3. **Scenarios:** write one per observable behaviour, derived from the success conditions, in given/when/then with concrete values.
   - Each governing-context requirement expressible as behaviour (legal, security, data integrity, domain constraint, prior decision) gets its own scenario.
   - List the behaviours each planned contract suite covers.
4. **Feasibility:** design each scenario test-first on paper: the seams and ports used, order, fixtures, guards met and host needs. Correct a scenario that contradicts a guard, a constraint or a process rule now, never in 5.5.
5. **Size:** split by domain when the map demands it ([Lane, size and splitting](SLICE-DISCIPLINE.md#lane-size-and-splitting)).
6. **Delivery package** when the implementer did not prepare the slice ([Delivery package](#delivery-package)). **Pre-mortem** for transversal slices.
7. **Approval:** present the slice under **Slice approval presentation** in [SPEC-LAYOUT](SPEC-LAYOUT.md#files).
   - Present it even when every seam was reused or an earlier version was approved.
   - In a `lite` project, use **Lite approval** instead.
   - A project without a slice-deck renderer adopts one first (**Deck generation** in [SPEC-LAYOUT](SPEC-LAYOUT.md#files)).
   - On recovery, reuse a recorded approval only if it covers the current content.

This step writes scenarios, **no executable tests**.

**Done when:** every success condition and context requirement has a feasible scenario at a listed seam, and the user approved the presented Markdown version. Apply the 5.4 transition ([STATUS-REGISTER](STATUS-REGISTER.md#how-the-process-writes-the-register)).

**Commit (phase 1):** the spec, the approval HTML (none in `lite`), the register, and the wiki pages and `CONTEXT.md` terms from preparation. Add the renderer when this approval adopted it.

- The commit lands on the integration branch, written by the integrator and serialized with integrations.
- A responsible who is not the integrator hands the approved files over to the integrator.
- This commit is the slice's **base**.

## Impact map

Close the map with tools, not by reading: a call graph or an exhaustive literal search, plus the catalog of the real migrated database.

Each point records:

- its `file:line`;
- a classification: changes, consumer to adapt, proved untouched, or other slice;
- its proof: a scenario, a guard or an existing test.

Declare the closure's limits: what the tools cannot see, such as reflection, dynamic SQL, generated code and external consumers.

A full map covers:

- direct and transitive callers of touched signatures and seams;
- tests, fakes, stubs and fixtures;
- guards and pins (hash, regex, text, count);
- database defaults, triggers, functions, constraints and lock order;
- cross-cutting effects (time, roles, audit, events, tenancy), each classified by the approved semantics and the project's conventions;
- collisions with slices prepared or in execution;
- the tests' host needs (toolchain, images, ports, browser).

The RED of 5.5 confirms the map; it does not discover it.

## Delivery package

The package is required when the implementer did not prepare the slice (another agent, a swarm, a person):

1. **Dispositions** for every map point: wire it (citing the spec rule), leave it untouched, assign it to another slice (naming which), or route it to a migration or amendment. Every point gets a disposition; none stays "to decide".
2. **Cross-cutting conventions**, cited from `architecture.md`. A missing convention is decided there, once.
3. **Owners** of each shared field and path in a chain or feature, fixed before its first slice starts.
4. **Pre-authorised change classes** beyond M1–M3 ([Mechanical amendment classes](IMPLEMENTATION.md#mechanical-amendment-classes)). Each is stated exactly, or as one of the project's standing classes cited with its perimeter. Anything else is an exception, reported in one list.
5. **Setup proof:** a skeleton test run once in the real environment (toolchain, images, permissions, fixtures, ports, browser). Fix failures before handoff.
6. **Guard plan:** the affected guards and how each changes (M2 or strengthening), approved with the spec.
7. **Pre-mortem** by an independent reviewer before approval. It looks for impossible scenarios, points without a disposition, collisions, and missing fixtures, resources or classes.
