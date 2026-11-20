# Preparation with subagents

Reached when the slice's phase 1 is not closed. The lead takes the slice through Zafir 5.1–5.4 by the Zafir `PREPARATION.md`, which stays authoritative; this file adds only who does what. Read it with the project's preparation rules before the first step. The preparation works in `.worktrees/<slice>-preparation` on `prep/<slice>`, and a setup proof in `.worktrees/<slice>-setup`, as [Start](SKILL.md#start) names them.

## Roles

- **The lead** owns the spec, the decisions it may take and the questions it may not. It writes or edits the spec, the impact map and the delivery package, or gives a subagent one bounded piece at a time.
- **Consultant subagents** advise. Each starts with a clean context and one written brief: the question, the paths and sha256 of the frozen inputs, and the output file. Use them for the independent readings Zafir asks for: refinement and stress-test (5.2), the review of the seams and scenarios, and the pre-mortem before 5.4. A consultant never read or wrote the version it reviews, and each review uses a new one.
- **The requester** decides every question the project reserves for the owner, and approves 5.4. The lead never approves its own spec.

## Steps

1. **5.1 Pick or create the slice.** Confirm the slice, its dependencies and its readiness on the register. Done when the slice row and spec path exist and every dependency is either done on main or named as a blocker to the requester.
2. **5.2 Refine and stress-test.** Draft the spec, then have a consultant subagent grill it (the `grilling` skill where available). Fix what it finds; bring every product, legal, security, guard, migration or ceiling question to the requester as a decision round (options, consequences, a recommendation). Done when no question is open except those waiting on the requester.
3. **5.3 Documentation in sync.** Update the documents and wiki pages the project requires for the slice. Done when the project's documentation checks pass on the preparation branch.
4. **5.4 Seams and scenarios.** Agree the seams, write the acceptance scenarios, the impact map and the delivery package, and prove the setup the project requires. A clean consultant reviews the package; then a different clean consultant runs the pre-mortem. Fix the findings and keep a short disposition of each. Done when both pass or every remaining note has a disposition.
5. **Approval.** Send the requester the 5.4 package: the spec path and sha256, the LIA or legal entries the project keeps, the review and pre-mortem verdicts with their paths, and the decisions still open. Wait for an explicit approval of those exact bytes. A change after approval goes back to the requester as a diff for confirmation.
6. **Phase 1.** Commit the approved documents as the phase 1 commit the project defines, with the register row updated by ID. Orchestrated: hand the phase 1 SHA to the orchestrator, who integrates it and admits the slice. Standalone: ask the user whether to integrate it now or to continue on the branch. Done when the requester confirms the slice is implementable; then return to [Start](SKILL.md#start).
