# Implementation — Steps 5–6

Procedure under [SKILL.md](SKILL.md), using its [Terms](SKILL.md#terms). Steps 5.1–5.4 are in [PREPARATION.md](PREPARATION.md). Register transitions follow [STATUS-REGISTER.md](STATUS-REGISTER.md#how-the-process-writes-the-register). [CONCURRENCY.md](CONCURRENCY.md) governs admission when more than one slice is in execution, and every integration.

## Step 5 — Implement a slice

**Entry:**

- Refinement (5.1–5.4) runs only while the row is `specifiable`.
- Productive work (5.5) requires `implementable` on the authoritative register and a passed freshness check ([Just-in-time and freshness](PREPARATION.md#just-in-time-and-freshness)).
- Scenarios within a slice run sequentially.
- Phase-2 commits go on the slice branch, which starts at `base` ([Own branch, always](SKILL.md#standing-rules)).

### 5.5 Plan, write the slice's tests, then implement one test at a time

5.5 has three stages, run in this order. Each stage ends on its `verify:` check.

#### Stage 1 — Plan

Write the implementation plan from the delivery package. When the implementer prepared the slice, write it from the spec instead. The plan lists:

- the tasks;
- the scenarios and tests of each task;
- the write scope;
- the order: by dependency, then by risk.

The plan goes in the slice spec and is committed with the first phase-2 commit. It is the resume point inside stage 3 ([Reading the register](STATUS-REGISTER.md#reading-the-register)).

verify: every test maps to a scenario, and every scenario to a task.

#### Stage 2 — Write all the slice's tests (the RED)

1. **Contract skeleton**, only when the seams are new types or signatures.
   - Write the declarations the spec names.
   - Every behaviour body fails closed: an explicit not-implemented error, with no effects. A body never returns a successful placeholder.
   - Adapt consumers under M1 so the tree compiles.

   **Commit (phase 2, skeleton).**
2. **Test plumbing**, only when fixture mechanics keep the tests from their target operation.
   - Make one bounded commit holding only that plumbing. Examples: in-memory seeding; observation and snapshot/restore of test state; hooks that load the *given* facts; a test-only bridge that reaches existing bodies while a new constructor still fails closed.
   - Target rules stay fail-closed.
   - A bridge or arrangement that bypasses a constructor is removed by the task that implements that constructor. That task adds a test that fails while the bypass survives.

   **Commit (phase 2, plumbing).**
3. **The battery:** write the tests of every scenario of the slice at their seams. Run the whole set once and keep the **RED log**, classifying each test:
   - **causal red**: it fails for its own reason (its assertion, a missing behaviour). This is the target state.
   - **wrong red**: it fails to compile, or fails for another reason. Fix the test and re-run.
   - **non-causal**: the plumbing still cannot bring it to its target. It stays in the battery and never counts as its own RED. It gets an omission mutant at its green step.
   - **already green**: record it. Its fact gets an omission mutant at its green step.

   verify: no wrong red remains, and every test appears in the RED log with its class.
   **Commit (phase 2, tests):** the whole battery and its RED log, alone.

#### Stage 3 — Turn the tests green one at a time

Take the red tests in the plan's order, one test (or one small cohesive group) at a time:

1. Make the smallest correct change that turns it green.
2. verify: it is green and every earlier green test still is. A test that turned green without new code gets an omission mutant.
3. **Commit (phase 2, green step):** the production code that turned those tests green. One commit may instead hold a group of steps forming one logical change.

A purely mechanical change (M1: a rename, an argument propagated to consumers) may be done in one batch.

**Refactor**, once every test of the slice is green and before 5.6 and the review: apply the `ponytail` skill to the slice's diff. Behaviour stays as it is, and every test stays green.

verify: every test is green after the refactor.
**Commit (phase 2, refactor):** the refactor alone. When `ponytail` changes nothing, record that in the plan instead.

Rules that hold across the three stages:

- **One causal proof per fact.**
  - The slice RED (causal) followed by the test's green is the proof. Add no mutant for that fact.
  - A fact without its own causal RED gets one omission mutant: show a causal RED, then restore and reach GREEN. Such a fact was already green in the RED, turned green without new code, or was done in a batch.
  - Guards, pins and structural proofs keep their mutants.
  - Map points are wired in batches. The RED confirms the impact map.
- **Dependencies:** reuse existing implementations. For an unavailable one, the contract suite, the contract and the simplest passing placeholder come first ([Contracts and placeholders](SLICE-DISCIPLINE.md#contracts-and-placeholders)). They are the first tests and the first green step.
- **Derived scenarios:** an in-scope edge, invariant or regression risk found while implementing:
  - is added to the spec, marked derived;
  - gets its test (RED, then green);
  - is committed with its step.

  A discovery that changes expected behaviour or scope stops the loop for a user decision. Never redefine scope through a test.
- **Spec gaps:** a point outside the impact map is a spec gap. Record its type (incomplete closure, impossible scenario, hidden effect) and its cost. For a handed-off slice, also record the delivery-package item that failed.
- **Design and sources:**
  - Behaviour sits behind the seams in architecture and design. An architecture change returns to 3.1.
  - Resolve domain terms with the user and record them in `CONTEXT.md`.
  - Implement the adopted style ([What adoption means in Step 5](ARCHITECTURE-GUIDELINE.md#what-adoption-means-in-step-5) for DDD).
  - Read lockfiles and installed versions. Ground framework code in its official documentation, and flag unverified facts.
  - UI follows the project's existing components and screens.
- **Execution grants:** when an execution system grants permissions, one grant covers a whole batch of facts: edit, focused runs, proofs, restore, final GREEN and report. Ask for one grant per batch, never one per step.

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
commit 5  refactor with ponytail: S1-S3 still green
gate      whole gate (5.6), review (5.7), phase 3
trailers  commits 1-5: "Slice: invoicing-03" and "Phase: 2"
```

**Done when:** every original and derived scenario has a passing test, and the refactor is committed or recorded as empty.

### Scope changes

- **Within the envelope** (its paths, or its declared areas): proceed. Record new paths and report them.
- **Inside a [mechanical amendment class](#mechanical-amendment-classes):** apply the edit without a new 5.4.
- **A new area:** the responsible reviews it before the edit.
  - If it brings behaviour, a contract, a scenario or compliance, it is a 5.4 amendment.
  - Otherwise, record it and report it.
- **A discovered dependency** on another slice in execution pauses this slice ([Admission](CONCURRENCY.md#admission)).

### Mechanical amendment classes

These classes pre-authorise edits outside the envelope, without a new 5.4:

- **M1 — consumer propagation:** a test, fake or stub that fails only because an approved signature or constructor changed. The edit may only:
  - pass the new argument or dependency (a fixed fixture or the existing real source);
  - add the import;
  - add the parameter to the fake, forwarded or ignored.

  Assertions stay unchanged.
- **M2 — pinned value:** a guard pinning a hash, regex, text or count of approved bytes. Only the pinned value changes, to the approved bytes. Everything else stays byte-identical, and the guard still fails on the same regression.
- **M3 — migration renumbering**, by the integrator, where migration versions come from file names. A migration that no shared database has applied takes the next free version. Only references to its number change. A number used before integration is provisional; the integrator renumbers it under M3.
- **Spec and project classes:** the classes listed in the slice's delivery package, or in a project decision it cites. Each applies exactly as written, with the slice's concrete perimeter (callers, paths, symbols, fixtures, proofs).

Conditions for every class:

- A path that fits a class entirely is edited without waiting for the responsible. Any other path is reviewed by the responsible first.
- A reviewer who did not write the diff confirms the class in writing.
- A dated note in the spec and in the register names the class, the paths and the change. The project's envelope record may hold the note instead of the register.
- The change is reported.

Beyond M3's renaming and number references, M1–M3 never cover:

- production code or migrations;
- specs or register semantics;
- removed, skipped or weakened assertions, or new tests;
- another slice's semantics.

In doubt, the edit is a 5.4 amendment.

### 5.6 Verify

Run the **whole gate** ([Green means the whole gate](SKILL.md#green-means-the-whole-gate)). One passing test is not the gate.

**Done when:** every applicable check passes. Record `verification passed`, `evidence.tests`, and `evidence.browser` when the browser check ran. No commit: the evidence goes with phase 3.

### 5.7 Review before done

Review `git diff <base>` against the spec and the Four Principles. The diff starts at the row's `base` and covers committed and uncommitted changes.

- Local, transversal and R-lane slices are reviewed by someone who did not write the diff ([independent reviewer](SKILL.md#roles)).
- Trivial, lite and bug-fix work may be self-reviewed.

Check **all**:

- Every changed line traces to slice scope or a mandatory artefact. Exclusions hold. There is no out-of-scope refactoring.
- Every original, derived and context scenario has a passing test, and every test maps to a scenario. Derived scenarios changed neither scope nor behaviour without a recorded decision.
- No guard or test was weakened. Amendments stayed within their classes.
- The adopted style holds (the review checks in [What adoption means in Step 5](ARCHITECTURE-GUIDELINE.md#what-adoption-means-in-step-5)).
- [Slice discipline](SLICE-DISCIPLINE.md) holds: no existing implementation is wrapped; every placeholder is registered; no security placeholder sits in a deployable build without its permitted decision.
- Every contract suite passes against every implementation. Replaced placeholders are deleted.
- Every added migration ran up and down on a disposable database. An irreversible migration instead has its alternative documented and, where possible, rehearsed.

**Task reviews** are optional, by project decision. They are short reviews of each task during 5.5: its tests in the RED, then green with its own code. They catch defects early and never replace this review.

Fix the findings. A fix touching code, tests, migrations or build inputs re-runs the whole gate ([When it runs](SKILL.md#green-means-the-whole-gate)).

**Done when:** every item holds. Record `evidence.reviews`.

**Commit (phase 3):** review fixes, the final spec and the register (`implementation done`, dependents recomputed), on the slice branch. The commit stays provisional until the integration commit ([Integration queue](CONCURRENCY.md#integration-queue)).

## Step 6 — Close the feature

**Entry:**

- Every slice of the feature is authoritatively `done` or `won't-do`.
- All its branches are integrated, or disposed of by recorded decision.

The integrator writes the closure, serialized with integrations. Closure does not wait for other features.

1. **Placeholders:** run the active-placeholder query ([Reading the register](STATUS-REGISTER.md#reading-the-register)).
   - Each active placeholder is replaced, or kept by recorded decision.
   - A decision keeping a security placeholder covers deployable builds, within the hard constraints.
   - An undecided placeholder blocks closure.
2. **Gate:** the whole gate is green, including contract suites against every remaining implementation.
3. **Specs:** add implemented status lines at the top of the brainstorm and the design, without rewriting them. Regenerate changed decks.
4. **Knowledge:** write durable outcomes to the wiki. `CONTEXT.md` matches the code's vocabulary.
5. **Register:** the feature row gets, under invariants 8–9 ([Invariants](REGISTER-SCHEMA.md#invariants)):
   - `verification passed`, `implementation done`, `nextAction` "None";
   - `evidence.commits` = the integration SHAs of its slices;
   - `evidence.tests` = the closing gate's commands;
   - a closing note.
6. **Metrics:** derive them from Git, without a new register. Use the [metrics per integration](CONCURRENCY.md#batches), or the commits themselves:
   - admission-to-integration time per slice (from admission into execution to its integration commit);
   - amendments and spec gaps by type;
   - stops;
   - integration conflicts and time in queue;
   - the share of docs-only commits.

   Summarise them in the closing note. Review them periodically with the user, including the concurrency cap.

**Done when:** all six hold.

**Commit:** one closing commit with status lines, regenerated decks, register, wiki and vocabulary updates.
