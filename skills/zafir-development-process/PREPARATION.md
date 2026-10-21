# Preparation — Steps 5.1–5.4

Procedure under [SKILL.md](SKILL.md). It takes a planned slice to an approved, executable spec — the phase-1 commit — without writing tests or code, and defines the freshness check at admission.

## Proportionality

Depth follows the slice's lane. The table binds both ways: never skip what the lane requires, never impose what it does not.

| Element | Lite | Local | Transversal or first of a chain |
| --- | --- | --- | --- |
| Impact map | — | short: callers of touched signatures, tests and fakes, guards, database objects of touched tables | full (*Impact map*) |
| Feasibility design | one line per scenario | per scenario | per scenario |
| Delivery package, when the implementer did not prepare the slice | — | items 1, 4, 5 | all items |
| Pre-mortem | — | — | independent reviewer |

R-lane work follows SHORT-PATHS; bug fixes and trivial changes need none of this.

## Decision round

One round each at preparation, admission, execution and integration. Each question gives options, consequences and a recommendation; ask every open question whose prerequisites are answered. Outside the round, interrupt only for what blocks work in progress. Mechanism decisions (how, not what) are explained and recorded, not asked; the user may reverse them. At the third occurrence of the same decision type, propose a class authorisation, recorded like a pre-authorised class.

## Just-in-time and freshness

- Prepare a slice that depends, directly or transitively, on one in execution only when that dependency completes phase 3 or is integrated, on the then-current integration branch. Independent slices do not wait.
- An approved spec waiting for admission is not revalidated. At admission, diff the integration branch since the approval commit against the map and envelope: no effect on behaviour, scenarios or contracts → record and start; touches the map → update the map, no new approval; changes a scenario or contract → **one** amendment through 5.4, with every consumer closed.

## 5.1 Pick or create the slice

Locate the mini-spec in `docs/specs/<feature-slug>/slices/` and its row; confirm its lane. Behaviour outside every approved brainstorm returns to Step 1. A new slice within an approved plan is created now under Step 4's rules.

**Done when:** the slice is located and registered within approved scope, or work has returned to its missing gate. No commit.

## 5.2 Refine and stress-test the slice

**Entry:** before any test or code.

List what the brainstorm, architecture, design and earlier slices settled; do not ask it again. Look up codebase facts; ask only product and risk gaps and hard-to-reverse decisions, in the decision round. Check settled decisions against governing context; write durable ones to the wiki, link them from the spec, and resolve `governingContext`. An unsettled gap makes the row `spec blocked` with the blocker in `qualifier` and `nextAction`. With no gaps, record **no open decisions**.

**Done when:** the spec holds the refined understanding and every gap is settled or blocked. Artefacts go into phase 1.

## 5.3 Keep documentation in sync

A standing duty through Step 5: whenever a slice changes state, update its row (STATUS-REGISTER) and spec, committed in the phase that caused it. An implemented spec is never rewritten to change scope; new behaviour is a future slice; a derived scenario within scope is not a scope change.

## 5.4 Agree the seams, then define the acceptance scenarios

1. **Impact map** at the lane's depth.
2. **Seams:** list the public interfaces where behaviour is observed, each with its reason. Ask only about a seam that is new, public-facing, crosses a module or context boundary, or is uncertain; reuse tested seams without asking.
3. **Scenarios:** one per observable behaviour, from the success conditions, in given/when/then with concrete values. Each governing-context requirement expressible as behaviour (legal, security, data integrity, domain constraint, prior decision) gets its own scenario. List the behaviours each planned contract suite covers.
4. **Feasibility:** design each scenario test-first on paper — seams and ports used, order, fixtures, guards met, host needs. A scenario that contradicts a guard, a constraint or a process rule is corrected now, never in 5.5.
5. **Size:** split by domain when the map demands it (SLICE-DISCIPLINE *Lane, size and splitting*).
6. **Delivery package** when the implementer did not prepare the slice; **pre-mortem** for transversal slices.
7. **Approval:** present the slice under SPEC-LAYOUT's **Slice approval presentation** (**Lite approval** in a `lite` project), even when every seam was reused or an earlier version was approved; a project without a slice-deck renderer adopts one first (SPEC-LAYOUT *Deck generation*). On recovery, reuse a recorded approval only if it covers the current content.

This step writes scenarios, **no executable tests**.

**Done when:** every success condition and context requirement has a feasible scenario at a listed seam, and the user approved the presented Markdown version. Apply the 5.4 transition (STATUS-REGISTER).

**Commit (phase 1):** spec, approval HTML (none in `lite`), register, wiki pages and `CONTEXT.md` terms from preparation, plus the renderer when this approval adopted it. It lands on the integration branch, written by the integrator and serialized with integrations; a responsible who is not the integrator hands over the approved files. This is the slice's **base**.

## Impact map

Closed with tools, not by reading: a call graph or exhaustive literal search, and the catalog of the real migrated database. Each point records `file:line`, a classification (changes, consumer to adapt, proved untouched, other slice) and its proof (scenario, guard or existing test). Declare the closure's limits — what the tools cannot see (reflection, dynamic SQL, generated code, external consumers). A full map covers:

- direct and transitive callers of touched signatures and seams;
- tests, fakes, stubs and fixtures;
- guards and pins (hash, regex, text, count);
- database defaults, triggers, functions, constraints and lock order;
- cross-cutting effects (time, roles, audit, events, tenancy), each classified by the approved semantics and the project's conventions;
- collisions with slices prepared or in execution;
- the tests' host needs (toolchain, images, ports, browser).

The RED of 5.5 confirms the map; it does not discover it.

## Delivery package

Required when the implementer did not prepare the slice (another agent, a swarm, a person):

1. **Dispositions** for every map point: wire (citing the spec rule), leave untouched, other slice (which), or migration/amendment. Nothing stays "to decide".
2. **Cross-cutting conventions** cited from `architecture.md`; a missing one is decided there, once.
3. **Owners** of each shared field and path in a chain or feature, fixed before its first slice starts.
4. **Pre-authorised change classes** beyond M1–M3 (IMPLEMENTATION *Mechanical amendment classes*), each exact, or the project's standing classes it cites with their perimeter; anything else is an exception, reported in one list.
5. **Setup proof:** a skeleton test run once in the real environment (toolchain, images, permissions, fixtures, ports, browser); fix failures before handoff.
6. **Guard plan:** affected guards and how each changes (M2 or strengthening), approved with the spec.
7. **Pre-mortem** by an independent reviewer before approval: impossible scenarios, points without disposition, collisions, missing fixtures, resources or classes.
