# Short paths

Read at SKILL.md Step 0. Where there is no decision to make visible, ceremony is unnecessary; every path stays test-first, reviewed and checked against governing context. A short path overrides only the steps it names; SKILL.md's standing rules always apply.

## Trivial change

A request is trivial when **all** hold:

- it introduces or changes no domain term;
- it declares no contract and adds or refines no placeholder;
- it changes nothing in `architecture.md` and adds no security rule;
- its tests can be written from the request alone;
- it touches at most three source files, tests excluded.

It follows the [bug-fix workflow](#bug-fix-workflow) from step 2, on its own branch, and adds a register note naming the feature it touches, committed with the fix (without a feature, the commit message is the record). No brainstorm, slice spec or grilling. If any condition is in doubt, ask; if a decision appears mid-way, stop and enter Step 1.

## Behaviour-free refactor (R lane)

A refactor or mechanical mass change, with no limit on files, qualifies when it changes no domain term, scenario, approved seam, security rule, external contract (API, schema or migration, file formats, events) or compliance artefact, and the tests pass before and after without changed assertions (except mechanical amendment classes M1/M2).

1. **Technical note** in the project's decisions location: goal, invariant preserved, areas, verification. Approved in the conversation; no deck.
2. **Own branch;** whole gate green at the base and at the end.
3. **Independent review** against the criteria above.
4. Integrate under CONCURRENCY when other slices are in execution, else `git merge --no-ff`, with a register note naming the feature.

One agent suffices. A behaviour, contract or compliance decision stops the lane and enters the full workflow. In doubt it is not R: ask; the user may reclassify.

**Commit:** the note with the first change; each logical step after a green gate; the merge.

## Lite project

A project profiled `lite` (SPEC-LAYOUT *Profile and architecture style*) runs at reduced weight:

- Step 1 as usual.
- Step 2: one `brainstorm.md` for the project, approved once; later CRUD additions enrich it as a section, approved by path before slicing, unless the user asks for a separate feature.
- Step 3: `architecture.md` holds the header (`Profile: lite`, `Architecture style: none` unless chosen), stack and constraints; no module map. `design.md` is deferred by default, without asking.
- Step 4: slices and tiers as usual.
- Step 5: no impact map, delivery package or pre-mortem; seams and scenarios first; grilling only when a slice has a decision, in one round; placeholders registered; the slice approved by its Markdown (SPEC-LAYOUT *Lite approval*). Then the three stages of 5.5 as usual: plan, the whole battery and its RED log, green one test at a time. Two folds are allowed:
  - **Phase 1 into the first phase-2 commit** (skeleton, plumbing or tests, whichever comes first), on the slice branch with trailer `Phase: 2`. `base` is that commit's parent, the commit the slice branch starts from, so `git diff <base>` covers every slice commit; the freshness check diffs from `base`.
  - **Phase 3 into the last green step:** the gate (5.6) and review (5.7) run on the uncommitted final tree; that commit then holds the last green change, review fixes, final spec and register, with trailer `Phase: 3`.

## Bug fix workflow

Bug fixes skip the slice workflow and keep its discipline:

1. **Diagnose**, on the fix's own branch (SKILL.md *Own branch, always*). Before any hypothesis, build a feedback loop that goes red on this exact bug (test, script, request) and minimise the reproduction. Then rank hypotheses, test one variable at a time, find the root cause. If the request is really new functionality, switch to Step 1.
2. **Test.** Adjust the covering test, or write one that fails for this bug at the seam where it occurs (for a trivial change: one that fails for the requested behaviour).

   **Commit:** now, while it fails — the test alone; the message names the bug.
3. **Patch narrowly.** Only the code the fix requires.
4. **Gate and review.** Whole gate green; diff reviewed against Surgical Changes.
5. **Governing context.** Check the fix against it.

   **Commit:** the verified fix, with the register note for a trivial change and any `CONTEXT.md` or wiki edit it caused.
6. **Integrate** under CONCURRENCY when other work is in execution, else `git merge --no-ff` into the integration branch.

   **Commit:** the merge.

Done when the three commits exist and the gate is green on the integration branch.
