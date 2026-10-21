# Planning — Steps 1–4

Procedure under [SKILL.md](SKILL.md). Artefact paths and contents follow [SPEC-LAYOUT.md](SPEC-LAYOUT.md); register writes follow [STATUS-REGISTER.md](STATUS-REGISTER.md). A provisional lite profile switches to SHORT-PATHS *Lite project* immediately.

## Step 1 — Governing context check

**Entry:** before brainstorming any non-trivial project, feature or extension, brown-field included.

**Actions:** consult the wiki and repository (SKILL.md *Governing context*) and carry the relevant references into the brainstorm. Ask whether other context or sources exist; request missing files, or their placement in `docs/wiki/raw/` where that convention exists.

**Done when:** inputs are listed with what is still missing. No commit.

## Step 2 — Brainstorm

**Entry:** Step 1 done; mandatory for new projects and non-trivial features. A raw feature request enters here, not at slicing.

**Actions:** interview the user in iterations:

1. **Diverge:** restate the idea; ask who it serves, what success looks like, what is excluded; offer missed alternatives.
2. **Converge:** cluster answers, stress-test the leading direction against cost, value and assumptions, and challenge weak or overcomplicated ideas. Elicit objective, constraints, principles, non-goals and boundaries.
3. **Persist before continuing:** at the first iteration create `brainstorm.md` and the feature row (and the register if absent). After every answer, synthesis, pivot or decision, update the file before the next question. The file, not the chat, holds the conclusions; stop if it cannot be written.

`brainstorm.md` holds objective and user value; constraints, principles, non-goals and boundaries; alignment with governing context and wiki links; decisions, open questions, blockers and an iteration log. In brown-field work, inspect instructions, specs, code and docs and capture existing architecture and compatibility constraints.

**Profile:** as soon as the interview permits, propose `full` or `lite` (SPEC-LAYOUT), explain why, and record the answer as provisional; 3.1 confirms or changes it. Brown-field work with an `architecture.md` uses its profile.

**Approval / done:** the user approves `brainstorm.md` by path (deck path when generated); it becomes the spec of record.

**Commit:** on approval — brainstorm, optional deck, register, wiki pages.

## Step 3 — Design and architecture

**Entry:** approved brainstorm. Project architecture first, feature design second (SPEC-LAYOUT *Architecture vs feature design*).

### 3.1 Project architecture (`docs/specs/architecture.md`)

- **Green-field:** the first feature creates it. Ask about technical, organisational, performance and regulatory constraints, principles and binding technology choices. Confirm the profile. Offer ARCHITECTURE-GUIDELINE once, saying why it fits or not; record profile and style headers, and an adopted style as a Decisions entry. Let a small module map grow feature by feature.
- **Brown-field:** ask whether to revisit the architecture. If yes, iterate as above. If no, accept the code as baseline; without a spec, write a minimal observed stack, modules, seams and constraints labelled **observed baseline, not decided**, with the observed profile and style (`none` when none is evident) for the user to confirm.
- Place seams at deep modules: substantial behaviour behind small interfaces. Challenge fuzzy domain terms and record them in `CONTEXT.md` when kept.
- Record **cross-cutting conventions** the feature's slices will share, once, before slicing.

**Approval / done:** `architecture.md` has at least profile, stack and constraints, approved by path. Every change is approved; architecture is never deferred.

**Commit:** on approval — architecture, optional deck, feature `architecture` state, `CONTEXT.md` (and `CONTEXT-MAP.md` when the style uses it), wiki deliberation pages.

### 3.2 Feature design (`docs/specs/<feature-slug>/design.md`)

Describe modules and seams touched or created, fit and deviations, referencing the architecture rather than restating it; an architecture change returns to 3.1 first. Iterate until aligned or until the user explicitly defers design; record a deferral in the brainstorm and feature row.

**Approval / done:** `design.md` approved by path, or deferred (lite defers by default).

**Commit:** on approval or deferral — design, optional deck, feature `design` state, brainstorm when recording deferral, wiki pages.

## Step 4 — Plan: cut into slices

**Entry — all three gates:** approved brainstorm; architecture with profile, stack and constraints, consistent with the brainstorm and approved if changed; design approved or deferred. A missing gate returns to its step. Slices derive from approved specs, never from raw requests or chat.

**Actions** (read [SLICE-DISCIPLINE.md](SLICE-DISCIPLINE.md) first):

- Write each numbered mini-spec under `docs/specs/<feature-slug>/slices/` with SPEC-LAYOUT's *Slice spec contents*, including its lane and envelope forecast.
- For a chain of dependent slices, name the owner of each shared field and path now.
- Recommend an order with reasons; the user decides. One register note records recommendation, reasons, decision and lanes.
- Register every slice in the decided order (STATUS-REGISTER *How the process writes the register*): real dependencies only, no artificial predecessor or join edges (Z1); `parallelAllowed` per the project's concurrency decision (CONCURRENCY *Prerequisites*), asked once per project, never per slice.

**Done when:** every mini-spec exists, the order is decided, and every slice has a validated row.

**Commit:** when the plan is agreed — slice specs, register, planning wiki pages. A later plan revision uses this marker for the changed plan artefacts only, written by the integrator when slices run on branches.

Next: PREPARATION.md (5.1–5.4), or the applicable short path.
