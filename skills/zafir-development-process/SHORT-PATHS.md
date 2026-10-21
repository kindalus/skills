# Short paths

Read at [Step 0](SKILL.md#step-0--apply-this-skill), with [Terms](SKILL.md#terms) for the vocabulary. Where there is no decision to make visible, ceremony is unnecessary. Every path still stays test-first, reviewed and checked against governing context. A short path overrides only the steps it names, and the [Standing rules](SKILL.md#standing-rules) always apply.

## Trivial change

A request is trivial when **all** hold:

- it introduces or changes no domain term;
- it declares no contract and adds or refines no placeholder;
- it changes nothing in `architecture.md` and adds no security rule;
- its tests can be written from the request alone;
- it touches at most three source files, tests excluded.

A trivial change follows the [bug-fix workflow](#bug-fix-workflow) from step 2, on its own branch. It needs no brainstorm, slice spec or grilling.

- It adds a register note naming the feature it touches, committed with the fix. Without a feature, the commit message is the record.
- If any condition is in doubt, ask.
- If a decision appears mid-way, stop and enter [Step 1](PLANNING.md#step-1--governing-context-check).

## Behaviour-free refactor (R lane)

A refactor or mechanical mass change qualifies, with no limit on files, when both hold:

- it changes no domain term, scenario, approved seam, security rule, external contract (API, schema or migration, file formats, events) or compliance artefact;
- the tests pass before and after without changed assertions, except under the mechanical amendment classes M1/M2 ([Mechanical amendment classes](IMPLEMENTATION.md#mechanical-amendment-classes)).

1. **Technical note** in the project's decisions location: goal, invariant preserved, areas, verification. It is approved in the conversation, with no deck.
2. **Own branch.** The whole gate is green at the base and at the end.
3. **Independent review** against the criteria above.
4. **Integrate** under [CONCURRENCY](CONCURRENCY.md) when other slices are in execution, otherwise with `git merge --no-ff`. Add a register note naming the feature.

One agent suffices. A behaviour, contract or compliance decision stops the lane and enters the full workflow. In doubt, the change is not R: ask, and the user may reclassify it.

**Commit:** the note, with the first change; then each logical step, after a green gate; then the merge.

## Lite project

A project profiled `lite` ([Profile and architecture style](SPEC-LAYOUT.md#profile-and-architecture-style)) runs at reduced weight:

- **Step 1** as usual.
- **Step 2:** one `brainstorm.md` for the project, approved once. Later CRUD additions enrich it as a section, approved by path before slicing, unless the user asks for a separate feature.
- **Step 3:** `architecture.md` holds the header (`Profile: lite`, and `Architecture style: none` unless one is chosen), the stack and the constraints, with no module map. `design.md` is deferred by default, without asking.
- **Step 4:** slices and tiers as usual.
- **Step 5:** seams and scenarios first, with no impact map, delivery package or pre-mortem.
  - Grilling happens only when a slice has a decision, in one round.
  - Placeholders are registered.
  - The slice is approved by its Markdown (*Lite approval* in [Files](SPEC-LAYOUT.md#files)).
  - Then the three stages of 5.5 run as usual: plan, the whole battery and its RED log, green one test at a time.

Two folds are allowed in Step 5:

- **Phase 1 into the first phase-2 commit** (skeleton, plumbing or tests, whichever comes first). That commit sits on the slice branch with trailer `Phase: 2`. `base` is its parent, the commit the slice branch starts from, so `git diff <base>` covers every slice commit. The freshness check diffs from `base`.
- **Phase 3 into the last green step.** The gate (5.6) and review (5.7) run on the uncommitted final tree. That commit then holds the last green change, review fixes, final spec and register, with trailer `Phase: 3`.

## Bug fix workflow

Bug fixes skip the slice workflow and keep its discipline:

1. **Diagnose** on the fix's own branch (*Own branch, always* in [Standing rules](SKILL.md#standing-rules)).
   - Before any hypothesis, build a feedback loop that goes red on this exact bug (a test, script or request), and minimise the reproduction.
   - Then rank hypotheses, test one variable at a time, and find the root cause.
   - If the request is really new functionality, switch to [Step 1](PLANNING.md#step-1--governing-context-check).
2. **Test.** Adjust the covering test, or write one that fails for this bug at the seam where it occurs. For a trivial change, write one that fails for the requested behaviour.

   **Commit:** now, while the test fails: the test alone, with a message that names the bug.
3. **Patch narrowly:** change only the code the fix requires.
4. **Gate and review.** The whole gate is green, and the diff is reviewed against Surgical Changes.
5. **Governing context.** Check the fix against it.

   **Commit:** the verified fix, with the register note for a trivial change and any `CONTEXT.md` or wiki edit the fix caused.
6. **Integrate** under [CONCURRENCY](CONCURRENCY.md) when other work is in execution, otherwise with `git merge --no-ff` into the integration branch.

   **Commit:** the merge.

**Done when** the three commits exist and the gate is green on the integration branch.
