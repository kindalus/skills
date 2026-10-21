# Implementation — Steps 5–6

Procedure under [SKILL.md](SKILL.md). Steps 5.1–5.4 are in [PREPARATION.md](PREPARATION.md). Register transitions follow [STATUS-REGISTER.md](STATUS-REGISTER.md); [CONCURRENCY.md](CONCURRENCY.md) governs admission when more than one slice is in execution, and every integration.

## Step 5 — Implement a slice

**Entry:** refinement follows `specifiable`; productive work (5.5) requires `implementable` on the authoritative register and a passed freshness check (PREPARATION *Just-in-time and freshness*). Scenarios within a slice run sequentially. Phase-2 commits go on the slice branch, which starts at `base` (SKILL.md *Own branch, always*).

### 5.5 Plan, write the slice's tests, then implement one test at a time

Three stages, in this order; each ends on its `verify:` check.

#### Stage 1 — Plan

From the delivery package (or the spec, when the implementer prepared the slice), write the implementation plan: tasks, the scenarios and tests of each, write scope, and order by dependency, then risk.

verify: every test maps to a scenario, and every scenario to a task.

#### Stage 2 — Write all the slice's tests (the RED)

1. **Contract skeleton**, only when the seams are new types or signatures: the declarations the spec names, every behaviour body failing closed (an explicit not-implemented error, no effects, never a successful placeholder), consumers adapted under M1 so the tree compiles.
   **Commit (phase 2, skeleton).**
2. **Test plumbing**, only when fixture mechanics keep the tests from their target operation: one bounded commit with only that plumbing, for example in-memory seeding, observation and snapshot/restore of test state, hooks that load the *given* facts, or a test-only bridge that reaches existing bodies while a new constructor still fails closed. Target rules stay fail-closed. A bridge or arrangement that bypasses a constructor is removed by the task that implements that constructor, with a test that fails while the bypass survives.
   **Commit (phase 2, plumbing).**
3. **The battery:** write the tests of every scenario of the slice at their seams, run the whole set once and keep the **RED log**, classifying each test:
   - **causal red** — fails for its own reason (its assertion, a missing behaviour): the target state;
   - **wrong red** — fails to compile or for another reason: fix the test and re-run;
   - **non-causal** — the plumbing still cannot bring it to its target: it stays, never counts as its own RED, and gets an omission mutant at its green step;
   - **already green** — recorded; its fact gets an omission mutant at its green step.

   verify: no wrong red remains, and every test appears in the RED log with its class.
   **Commit (phase 2, tests):** the whole battery and its RED log, alone.

#### Stage 3 — Turn the tests green one at a time

In the plan's order, for each red test (or small cohesive group):

1. Make the smallest correct change that turns it green.
2. verify: it is green and every earlier green test still is. A test that turned green without new code gets an omission mutant.
3. **Commit (phase 2, green step):** the production code that turned those tests green, or a group of steps forming one logical change.

A purely mechanical change (M1: a rename, an argument propagated to consumers) may be done in one batch.

Rules that hold across the three stages:

- **One causal proof per fact.** The slice RED (causal) followed by the test's green is the proof; add no mutant. A fact without its own causal RED (already green in the RED, green without new code, or done in a batch) gets one omission mutant showing a causal RED, then restore and GREEN. Guards, pins and structural proofs keep their mutants. Map points are wired in batches; the RED confirms the map.
- **Dependencies:** reuse existing implementations. For unavailable ones, the contract suite, contract and simplest passing placeholder (SLICE-DISCIPLINE) come first, as the first tests and the first green step.
- **Derived scenarios:** in-scope edges, invariants or regression risks found while implementing are added to the spec marked derived, get their test (RED, then green) and are committed with their step. A discovery that changes expected behaviour or scope stops the loop for a user decision; never redefine scope through a test.
- **Spec gaps:** a point outside the impact map is a spec gap; record its type (incomplete closure, impossible scenario, hidden effect) and cost, and for handed-off slices the package item that failed.
- **Design and sources:** behaviour sits behind the seams in architecture and design; an architecture change returns to 3.1. Resolve domain terms with the user and record them in `CONTEXT.md`. Implement the adopted style (ARCHITECTURE-GUIDELINE for DDD). Read lockfiles and installed versions; ground framework code in their official documentation and flag unverified facts. UI follows the project's existing components and screens.
- **Execution grants:** when an execution system grants permissions, one grant covers a whole batch of facts — edit, focused runs, proofs, restore, final GREEN and report — never one per step.

**Example** — scenarios S1 issue an invoice, S2 reject an invoice without lines, S3 a rejected invoice writes no audit record; the seam `IssueInvoice` is new:

```text
plan      T1 reject without lines (S2), then T2 issue, persist and audit (S1, S3); write scope: invoicing module and its tests
commit 1  skeleton: IssueInvoice declared; body returns NotImplemented, no effects
commit 2  tests S1-S3, run once; RED log:
            S1 causal red: expected an issued invoice, got NotImplemented
            S2 causal red: expected NoLines, got NotImplemented
            S3 already green: nothing writes audit yet -> needs an omission mutant at T2
commit 3  T1 reject an invoice without lines before any write: S2 green; S1 red; S3 green
commit 4  T2 issue, persist and audit: S1-S3 green
            S3 mutant: drop the early return -> S3 red -> restore -> S3 green
gate      whole gate (5.6), review (5.7), phase 3
trailers  commits 1-4: "Slice: invoicing-03" and "Phase: 2"
```

**Done when:** every original and derived scenario has a passing test.

### Scope changes

- **Within the envelope** (paths, or declared areas): proceed; record new paths and report them.
- **Mechanical amendment classes** (below): apply without a new 5.4.
- **A new area:** the responsible reviews before the edit; if it brings behaviour, a contract, a scenario or compliance, it is a 5.4 amendment; otherwise record and report.
- A discovered dependency on another slice in execution pauses this slice (CONCURRENCY *Admission*).

### Mechanical amendment classes

Pre-authorised edits outside the envelope, without a new 5.4:

- **M1 — consumer propagation:** a test, fake or stub that fails only because an approved signature or constructor changed. Only: pass the new argument or dependency (fixed fixture or the existing real source), add the import, add the parameter to the fake, forwarded or ignored; assertions unchanged.
- **M2 — pinned value:** a guard pinning a hash, regex, text or count of approved bytes. Only the pinned value changes to the approved bytes; everything else stays byte-identical and still fails on the same regression.
- **M3 — migration renumbering**, by the integrator, where migration versions come from file names: a migration no shared database has applied takes the next free version; only references to its number change. A number used before integration is provisional; the integrator renumbers it under M3.
- **Spec and project classes:** those listed in the slice's delivery package, or in a project decision it cites, each with the slice's concrete perimeter (callers, paths, symbols, fixtures, proofs), exactly as written.

Conditions: a path that fits a class entirely is edited without waiting for the responsible (otherwise the responsible reviews it first); a reviewer who did not write the diff confirms the class in writing; a dated note in the spec and in the register (or the project's envelope record) names class, paths and change; the change is reported. M1–M3 never cover (beyond M3's rename and number references) production code, migrations, specs, register semantics, removed, skipped or weakened assertions, new tests, or another slice's semantics. In doubt, it is a 5.4 amendment.

### 5.6 Verify

Run the **whole gate** (SKILL.md); one passing test is not it.

**Done when:** every applicable check passes; record `verification passed`, `evidence.tests` and `evidence.browser` when run. No commit; the evidence goes with phase 3.

### 5.7 Review before done

Review `git diff <base>` (committed and uncommitted, from the row's `base`) against the spec and the Four Principles. Local, transversal and R-lane slices are reviewed by someone who did not write the diff; trivial, lite and bug-fix work may be self-reviewed. Check **all**:

- every changed line traces to slice scope or a mandatory artefact; exclusions hold; no out-of-scope refactoring;
- every original, derived and context scenario has a passing test and every test maps to a scenario; derived scenarios changed neither scope nor behaviour without a recorded decision;
- no guard or test was weakened; amendments stayed within their classes;
- the adopted style holds (ARCHITECTURE-GUIDELINE review checks);
- SLICE-DISCIPLINE holds: no wrapped existing implementation, every placeholder registered, no security placeholder in a deployable build without its permitted decision;
- every contract suite passes against every implementation; replaced placeholders are deleted;
- every added migration ran up and down on a disposable database, or its irreversible alternative is documented and rehearsed where possible.

**Task reviews** (optional, by project decision): short reviews of each task during 5.5 (its tests in the RED, green with its own code) catch defects early; they never replace this review.

Fix findings; a fix touching code, tests, migrations or build inputs re-runs the whole gate (SKILL *When it runs*). **Done when:** every item holds; record `evidence.reviews`.

**Commit (phase 3):** review fixes, final spec and register (`implementation done`, dependents recomputed), on the slice branch. It is provisional until the integration commit (CONCURRENCY *Integration queue*).

## Step 6 — Close the feature

**Entry:** every slice of the feature is authoritatively `done` or `won't-do`, and all its branches are integrated or disposed of by recorded decision. Closure is written by the integrator, serialized with integrations; it does not wait for other features.

1. **Placeholders:** run the active-placeholder query (STATUS-REGISTER); each is replaced or kept by recorded decision; security retention covers deployable builds under the hard constraints. An undecided one blocks closure.
2. **Gate:** whole gate green, including contract suites against every remaining implementation.
3. **Specs:** add implemented status lines at the top of brainstorm and design without rewriting them; regenerate changed decks.
4. **Knowledge:** durable outcomes to the wiki; `CONTEXT.md` matches the code's vocabulary.
5. **Register:** feature `verification passed`, `implementation done`, `nextAction None`, `evidence.commits` = the integration SHAs of its slices, `evidence.tests` = the closing gate's commands, closing note (invariants 8–9).
6. **Metrics**, derived from Git without a new register (CONCURRENCY *Metrics per integration*, or the commits themselves): admission-to-integration time per slice, amendments and spec gaps by type, stops, integration conflicts and time in queue, share of docs-only commits. Summarise them in the closing note; review them periodically with the user, including the concurrency cap.

**Done when:** all six hold.

**Commit:** one closing commit with status lines, regenerated decks, register, wiki and vocabulary updates.
