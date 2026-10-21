# Planning — Steps 1–4

Procedure under [SKILL.md](SKILL.md); its vocabulary is in [Terms](SKILL.md#terms). Artefact paths and contents follow [SPEC-LAYOUT.md](SPEC-LAYOUT.md). Register writes follow [STATUS-REGISTER.md](STATUS-REGISTER.md). Once a project's provisional profile is lite, switch to [Lite project](SHORT-PATHS.md#lite-project) immediately.

## Step 1 — Governing context check

**Entry:** before brainstorming any non-trivial project, feature or extension, brown-field work included.

**Actions:**

1. Consult the wiki and the repository ([Governing context](SKILL.md#governing-context)).
2. Carry the relevant references into the brainstorm.
3. Ask the user whether other context or sources exist.
4. Request missing files, or ask for them to be placed in `docs/wiki/raw/` where that convention exists.

**Done when:** the inputs are listed, together with what is still missing. No commit.

## Step 2 — Brainstorm

**Entry:** Step 1 is done. The brainstorm is mandatory for new projects and non-trivial features. A raw feature request enters here, not at slicing.

**Actions:** interview the user in iterations.

1. **Diverge:** restate the idea. Ask who it serves, what success looks like and what is excluded. Offer alternatives the user missed.
2. **Converge:** cluster the answers. Stress-test the leading direction against cost, value and assumptions, and challenge weak or overcomplicated ideas. Elicit the objective, constraints, principles, non-goals and boundaries.
3. **Persist before continuing:**
   - At the first iteration, create `brainstorm.md` and the feature row, and the register if it does not exist yet.
   - After every answer, synthesis, pivot or decision, update the file before asking the next question.
   - The file, not the chat, holds the conclusions. Stop if the file cannot be written.

`brainstorm.md` holds:

- the objective and the user value;
- constraints, principles, non-goals and boundaries;
- alignment with governing context, with wiki links;
- decisions, open questions, blockers and an iteration log.

In brown-field work, inspect the repository's instructions, specs, code and docs, and capture the existing architecture and compatibility constraints.

**Profile:** as soon as the interview permits, propose `full` or `lite` ([Profile and architecture style](SPEC-LAYOUT.md#profile-and-architecture-style)) and explain why. Record the answer as provisional; 3.1 confirms or changes it. Brown-field work that already has an `architecture.md` uses its profile.

**Approval / done:** the user approves `brainstorm.md` by path (and the deck path when a deck was generated). It becomes the spec of record.

**Commit:** on approval — the brainstorm, the optional deck, the register and the wiki pages.

## Step 3 — Design and architecture

**Entry:** an approved brainstorm. Project architecture comes first, feature design second ([Architecture vs feature design](SPEC-LAYOUT.md#architecture-vs-feature-design)).

### 3.1 Project architecture (`docs/specs/architecture.md`)

**Green-field:** the first feature creates `architecture.md`.

- Ask about technical, organisational, performance and regulatory constraints, principles and binding technology choices.
- Confirm the profile.
- Offer [ARCHITECTURE-GUIDELINE](ARCHITECTURE-GUIDELINE.md) once, saying why it fits or does not.
- Record the profile and style headers. Record an adopted style as a Decisions entry.
- Let a small module map grow feature by feature.

**Brown-field:** ask whether to revisit the architecture.

- If yes, iterate as for green-field.
- If no, accept the code as the baseline. When no spec exists, write a minimal record of the observed stack, modules, seams and constraints, labelled **observed baseline, not decided**. Include the observed profile and style (`none` when none is evident) for the user to confirm.

**In both cases:**

- Place seams at deep modules: substantial behaviour behind small interfaces.
- Challenge fuzzy domain terms, and record the ones you keep in `CONTEXT.md`.
- Record, once and before slicing, the **cross-cutting conventions** the feature's slices will share.

**Approval / done:** `architecture.md` holds at least the profile, stack and constraints, approved by path. Every change to it is approved; architecture is never deferred.

**Commit:** on approval — the architecture, the optional deck, the feature's `architecture` state, `CONTEXT.md` (and `CONTEXT-MAP.md` when the style uses it) and the wiki deliberation pages.

### 3.2 Feature design (`docs/specs/<feature-slug>/design.md`)

- Describe the modules and seams the feature touches or creates, how it fits, and its deviations.
- Reference the architecture instead of restating it.
- An architecture change returns to 3.1 first.
- Iterate until aligned, or until the user explicitly defers design. Record a deferral in the brainstorm and in the feature row.

**Approval / done:** `design.md` is approved by path, or deferred. Lite projects defer by default.

**Commit:** on approval or deferral — the design, the optional deck, the feature's `design` state, the brainstorm when it records a deferral, and the wiki pages.

## Step 4 — Plan: cut into slices

**Entry — all three gates:**

1. an approved brainstorm;
2. an architecture with profile, stack and constraints, consistent with the brainstorm, and approved if it changed;
3. a design that is approved or deferred.

A missing gate returns to its step. Slices derive from approved specs only, never from raw requests or chat.

**Actions** (read [SLICE-DISCIPLINE.md](SLICE-DISCIPLINE.md) first):

1. Write each numbered mini-spec under `docs/specs/<feature-slug>/slices/` with the contents in [Slice spec contents](SPEC-LAYOUT.md#slice-spec-contents), including its lane and envelope forecast.
2. For a chain of dependent slices, name the owner of each shared field and path now.
3. Recommend an order with reasons; the user decides. One register note records the recommendation, the reasons, the decision and the lanes.
4. Register every slice in the decided order ([How the process writes the register](STATUS-REGISTER.md#how-the-process-writes-the-register)):
   - record real dependencies only, with no artificial predecessor or join edges ([Z1](REGISTER-SCHEMA.md#rules-z1z7));
   - set `parallelAllowed` from the project's concurrency decision ([Prerequisites](CONCURRENCY.md#prerequisites)), which is asked once per project, never per slice.

**Done when:** every mini-spec exists, the order is decided, and every slice has a validated row.

**Commit:** when the plan is agreed — the slice specs, the register and the planning wiki pages.

- A later plan revision uses this marker for the changed plan artefacts only.
- When slices run on branches, the integrator writes that revision.

Next: [PREPARATION.md](PREPARATION.md) (5.1–5.4), or the applicable short path.
