---
name: harness-status-bar
description: >-
  Canonical, responsive two-line terminal status bar layout specification for AI coding agent harnesses.
  Defines the exact layout structure, element anatomy (working directory, subscription tier, model, effort,
  context percentage and token size, 5-hour and 7-day usage quotas with reset countdowns), visual progress
  bars, ANSI color thresholds, and responsive width breakpoints. Use when designing, configuring, or
  implementing a status bar in any CLI/TUI agent harness (such as agy, Claude Code, Codex, Pi, or custom
  terminal wrappers) so every harness reproduces the same consistent layout.
license: MIT
---

# Harness Status Bar Layout Specification

This skill defines a portable, harness-agnostic specification for a two-line terminal status bar. It intentionally specifies **layout, element content, visual indicators, colors, and responsive breakpoints** — not a specific implementation. Each harness maps its own runtime telemetry and UI toolkit onto this specification so the user sees the same status bar across tools.

## Core Layout Principles

1. **Two content lines**, fixed semantic split:
   - **Line 1 (Session identity):** working directory on the left; subscription, model, and effort on the right.
   - **Line 2 (Context & quota telemetry):** context usage on the left; 5-hour and 7-day rolling quotas on the right.
2. **Edge-pinned `space-between` alignment:** left cluster pinned to the left edge, right cluster pinned to the right edge, and all remaining horizontal space placed in the middle:
   ```text
   gap = max(min_gap, inner_width - visible_len(left) - visible_len(right))
   line = left + (" " * gap) + right
   ```
   - `min_gap` is `2` columns.
   - `visible_len` MUST strip ANSI escape sequences and count terminal cell widths.
   - Avoid double-width emojis; use single-width Unicode glyphs (`●`, `▓`, `░`, `↻`, `·`, `│`) so alignment stays exact across terminals and fonts.
3. **Framing:** either a single-line Unicode box (`┌─┐│└─┘`, `inner_width = W - 2`) or a borderless top hairline (`─` across `W`, `inner_width = W`), keeping a 1-space outer margin on both left and right ends of each content line.

---

## Responsive Layout Blueprints

Let `W` be the current terminal or pane width in columns (updated on `SIGWINCH` / resize).

### Wide (`W ≥ 80`) — Full Mode

Example at `111 cols`:

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ~/workspace/src/github.com/acme/project                                [Ultra] gemini-4-neon · effort: high │
│ ● ctx 42% (420k/1M) ▓▓▓▓░░░░░░                                      ● 5h 18% ▓░░░░ ↻2h │ ● 7d 64% ▓▓▓░░ ↻3d │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Example at `80 cols` (all indicators remain visible; only `pwd` middle-truncates):

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ ~/.../acme/project                      [Ultra] gemini-4-neon · effort: high │
│ ● ctx 42% (420k/1M) ▓▓▓▓░░░░░░       ● 5h 18% ▓░░░░ ↻2h │ ● 7d 64% ▓▓▓░░ ↻3d │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Narrow (`60 ≤ W ≤ 79`) — Compact Bars & Effort

Example at `60 cols`:

```text
┌──────────────────────────────────────────────────────────┐
│ ~/.../acme/project          [Ultra] gemini-4-neon (high) │
│ ● ctx 42% (420k/1M) ▓▓░░░░   ● 5h 18% ↻2h │ ● 7d 64% ↻3d │
└──────────────────────────────────────────────────────────┘
```

### Ultra-Narrow (`W < 60`) — Essential Text Fallback

Example at `48 cols`:

```text
┌──────────────────────────────────────────────┐
│ .../project        [Ultra] gemini-4-neon (H) │
│ ctx 42% 420k/1M          5h 18% │ 7d 64% ↻3d │
└──────────────────────────────────────────────┘
```

---

## Element Specification

### Line 1 — Session Identity

| Element | Side | Format by Breakpoint (`Wide` / `Narrow` / `Ultra`) | Requirements & Fallback |
| :--- | :--- | :--- | :--- |
| **`pwd`** | Left | Full path with `~` for `$HOME` → middle-truncated (`~/.../parent/repo`) → `.../basename` | Compute `max_pwd = inner_width - visible_len(right) - min_gap - 2` (accounting for 1-space outer margins). Truncate middle segments first, always preserving the trailing directory name when possible. Style: muted/dim. |
| **`subscription`** | Right (1st) | `[<Tier>]` across all breakpoints (e.g., `[Ultra]`, `[Pro]`, `[Max]`, `[Team]`, `[API]`) | Short plan/tier badge before the model name. Style: subtle accent (e.g., dim cyan or magenta). Omit completely (including brackets) if the harness cannot determine the subscription tier. |
| **`model`** | Right (2nd) | `<model-id>` across all breakpoints (e.g., `gemini-4-neon`, `claude-opus-4-6`) | Active model identifier. Style: primary/emphasized (bold or default foreground). |
| **`effort`** | Right (3rd) | `· effort: <level>` / `(<level>)` / `(<initial>)` | Reasoning/thinking effort level (e.g., `low`, `medium`, `high`, `max`, `xhigh` → `L`, `M`, `H`, `M+`/`X`). Style: secondary. Omit cleanly when the active model or harness does not support effort levels. |

### Line 2 — Context & Usage Telemetry

| Element | Side | Format by Breakpoint (`Wide` / `Narrow` / `Ultra`) | Requirements & Fallback |
| :--- | :--- | :--- | :--- |
| **`context` (`ctx`)** | Left | `● ctx <pct>% (<used>/<max>) <bar10>` / `● ctx <pct>% (<used>/<max>) <bar6>` / `ctx <pct>% <used>/<max>` | Shows context window utilization percentage (integer, rounded) and token count in compact SI units (`k` for thousands, `M` for millions, e.g., `420k/1M`, `84k/200k`). Progress bar uses `▓` (filled) and `░` (empty): 10 cells wide in Wide mode, 6 cells in Narrow mode, omitted in Ultra-narrow. |
| **`usage_5h` (`5h`)** | Right (before `│`) | `● 5h <pct>% <bar5> ↻<rem>` / `● 5h <pct>% ↻<rem>` / `5h <pct>%` | Rolling 5-hour quota usage percentage, 5-cell progress bar (`▓`/`░`) in Wide mode, and reset countdown (`↻<rem>`). Because the window is `< 24h`, format `<rem>` in hours/minutes (e.g., `↻2h`, `↻45m`). |
| **`usage_7d` (`7d`)** | Right (after `│`) | `● 7d <pct>% <bar5> ↻<rem>` / `● 7d <pct>% ↻<rem>` / `7d <pct>% ↻<rem>` | Rolling 7-day quota usage percentage, 5-cell progress bar (`▓`/`░`) in Wide mode, and reset countdown in **remaining days** (`↻3d`, `↻1d`). When `< 24h` remain, switch to hours (`↻14h`, `↻<1h`). Preserve `↻<rem>` even in Ultra-narrow mode. |

### Progress Bar Calculation

Given usage percentage `pct` (`0..100`) and bar width `N` (`10`, `6`, or `5`):

```text
clamped = min(100, max(0, pct))
filled  = round(clamped / 100 * N)
if clamped > 0 and filled == 0:
    filled = 1
bar = ("▓" * filled) + ("░" * (N - filled))
```

### Reset Countdown Formatting

Given `remaining = reset_at - now`:

- For **`7d`** (day-scale window):
  - `remaining >= 24h`: ceiling or rounded days remaining, e.g. `↻3d`, `↻1d`.
  - `1h <= remaining < 24h`: hours remaining, e.g. `↻14h`.
  - `remaining < 1h`: minutes remaining, e.g. `↻35m` (or `↻0m` when elapsed).
- For **`5h`** (hour-scale window):
  - `remaining >= 1h`: whole hours (or rounded to nearest hour), e.g. `↻2h`.
  - `remaining < 1h`: minutes remaining, e.g. `↻45m`.
- If a reset timestamp is unavailable from the provider, omit `↻<rem>` cleanly without leaving trailing whitespace.

### Missing or Loading Telemetry

- Never display stale or fabricated numbers.
- If a quota endpoint is temporarily unavailable or not supported by a provider:
  - Prefer omitting the unsupported block (e.g., hide `5h` / `7d` entirely for pure pay-per-token API keys with no rolling window quotas) OR render `—` as placeholder while loading (`5h — │ 7d —`), keeping right alignment intact.

---

## Color Semantics (Usage Indicators)

Apply semantic color thresholds consistently to **`ctx`**, **`5h`**, and **`7d`**:

| Usage Range | Semantic Level | ANSI (256-color) | ANSI (16-color fallback) |
| :--- | :--- | :--- | :--- |
| **`0% – 59%`** | Healthy / Normal | `\x1b[32m` (green) | `\x1b[32m` (green) |
| **`60% – 79%`** | Caution | `\x1b[33m` (yellow) | `\x1b[33m` (yellow) |
| **`80% – 94%`** | High / Warning | `\x1b[38;5;208m` (orange) | `\x1b[31m` (red) |
| **`≥ 95%`** | Critical | `\x1b[1;31m` (bold red) | `\x1b[1;31m` (bold red) |

### What Receives Color

- **Usage-colored tokens:** the status dot (`●`), the numeric percentage (`42%`), and the filled bar cells (`▓▓▓`).
  - In Ultra-narrow mode (where `●` and bars are dropped), the percentage itself carries the semantic color.
- **Muted / dim (`\x1b[2m`):** `pwd`, empty bar cells (`░░░`), token size `(420k/1M)`, reset countdowns (`↻2h`, `↻3d`), labels (`ctx`, `5h`, `7d`), and separators (`·`, `│`).
- **Subscription badge:** subtle distinct accent (e.g., `\x1b[2;36m` dim cyan or `\x1b[2;35m` dim magenta).
- **Model name:** default foreground or bold (`\x1b[1m`).
- **`NO_COLOR` compliance:** if `NO_COLOR` is set in the environment, omit all ANSI color escape sequences while keeping `●`, `▓`/`░`, and layout alignment intact.

---

## Responsive Degradation Order

When reducing `W`, apply degradations strictly in this order before allowing any line to wrap:

1. **Middle-truncate `pwd`** dynamically on Line 1 to maintain `gap >= 2`.
2. **At `W < 80` (Narrow):**
   - Drop the 5-cell progress bars on `5h` and `7d`.
   - Shrink the `ctx` progress bar from `10` cells to `6` cells.
   - Compact `· effort: <level>` to `(<level>)`.
3. **At `W < 60` (Ultra-narrow):**
   - Drop the `ctx` progress bar and the `●` dots (retain color on percentages).
   - Drop parentheses around token size (`(420k/1M)` → `420k/1M`).
   - Drop the `5h` reset countdown (retain `7d` reset countdown `↻<rem>`).
   - Compact `(<level>)` to single-letter `(<initial>)`.
4. **Hard floor (`W < 42`):** truncate `pwd` to basename only and drop `subscription` badge before allowing a line wrap.

---

## Harness Verification Checklist

When implementing or updating a harness status bar from this spec, verify:

- [ ] Both lines fit strictly within `W` columns with no line wrapping at `W = 111`, `80`, `60`, and `48`.
- [ ] Left and right clusters touch the inner edges with all extra space centered between them (`gap >= 2`).
- [ ] Width calculation strips ANSI codes before computing padding.
- [ ] Resizing the terminal/pane re-evaluates breakpoints and re-renders cleanly.
- [ ] `ctx`, `5h`, and `7d` transition colors accurately at `60%`, `80%`, and `95%`.
- [ ] `7d` reset displays remaining days (`↻Nd`) when `>= 24h` remain and switches to hours/minutes below `24h`.
- [ ] Missing optional fields (`subscription`, `effort`, `5h`/`7d`, or resets) degrade cleanly with no broken separators or empty brackets.
- [ ] `NO_COLOR` disables ANSI escapes without breaking visual alignment.
