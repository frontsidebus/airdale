---
phase: 02-authority-safety-layer
plan: 10
subsystem: web-ui
tags: [authority, auth-08, auth-06, auth-02, browser, badge, degraded, b8, checkpoint-auto-approved]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    plan: 01
    provides: the four AuthorityReason members and the three AuthorityLevel members this renders
  - phase: 02-authority-safety-layer
    plan: 09
    provides: /api/status authority_level / authority_reason / authority / subsystems, and the command_advisory + command_withheld chat-WebSocket message types
provides:
  - "AUTH indicator in the status LED group carrying the level and, as text, the reason"
  - "Four explicit reason arms with no default fallthrough; an unrecognised reason or level renders verbatim"
  - "Server-reported `degraded` and client-side unreachable rendered as visually and textually distinct states"
  - "Level/reason transition toasts (AUTH-06) with the override cooldown excluded from the change key"
  - "cmd-advisory and cmd-withheld command outcomes, so executed / failed / advisory / withheld are four states"
  - "One reason-to-text mapping shared by the badge and the command result messages"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Verbatim-on-unknown rendering: a display map with no default arm, so an unrecognised value looks wrong instead of looking like a plausible known one"
    - "Content-independent flex basis for a variable-length badge, so its text never reflows its neighbours in a right-anchored header"
    - "Change key excludes the ticking value: an override cooldown counts down every poll without re-announcing itself"
    - "Client-side inference kept distinct from a server-reported failure of the same subsystem"
    - "Sliced-block node harness: exercise browser JS logic by extracting a self-contained block and driving it with DOM stubs, with no test framework and no build step"

key-files:
  created: []
  modified:
    - web/static/index.html
    - web/static/style.css
    - web/static/app.js

key-decisions:
  - "Advisory is cyan, not red: it is restricted, not faulted, and red is needed for the states that genuinely are"
  - "`degraded` gets a fault colour on top of its level class, because the transition toast fades after 3s and the badge is what remains"
  - "The client-side unknown state pulses; the server-reported degraded state does not, so the two red states separate at a glance"
  - "showCommandToast's second parameter generalised from a boolean to a tone, keeping boolean callers working unchanged"
  - "Rows for the two new outcomes are built from text nodes, not markup concatenation (T-02-10-03)"

requirements-completed: []

# Metrics
duration: 35min
completed: 2026-08-01
---

# Phase 02 Plan 10: Authority Display Summary

**The pilot can now see how much MERLIN may do to the aircraft and why, in the status bar, without asking — and the four situations that all produce `advisory` no longer look the same, because the reason is spelled out in text rather than implied by an LED colour that cannot carry four causes.**

## Performance

- **Duration:** ~35 min (base `3a58fa9` 16:09 → final task commit 17:42 local; active work ~35 min)
- **Tasks:** 2 implemented, 1 checkpoint (auto-approved — see the honest accounting below)
- **Files modified:** 3 (0 created, 3 modified; +401 / −2 lines)
- **Tests added:** 0 (see "The testing gap this plan does not close")

## Accomplishments

- **AUTH-08 is answerable by looking at the screen, not by reading JSON.** An `AUTH` indicator sits in the existing status LED group carrying the level as text plus a plain-English reason: `FULL (configured)`, `ADVISORY (pilot override, 87s left)`, `ADVISORY (command path down)`, `ADVISORY (authority subsystem degraded)`.
- **All four reasons have an explicit arm and there is no default fallthrough.** A fifth `AuthorityReason` would render as itself — verified by feeding the renderer a `quarantined` reason and watching `ADVISORY (quarantined)` come out rather than a plausible `configured`. This is the `tts_configured` failure mode CLAUDE.md names, applied to display code.
- **`degraded` no longer reads as a deliberate configuration.** It gets its own wording, its own fault colour, the failure toast tone, and `degraded_detail` in the `title` attribute — so the cause is recoverable without opening the server log. This is the distinction the whole phase turns on: "I was set to advisory" and "my authority subsystem failed to start and I restricted myself" call for opposite pilot responses.
- **A degraded server and an unreachable server are never the same badge.** The `pollStatus` catch sets an explicit `UNKNOWN (MERLIN unreachable)` rather than leaving a stale value, and that state is textually distinct, class-distinct and pulses, where the server-reported degraded does not. A stale `FULL` after the server goes away would assert MERLIN is armed when nothing on the page knows whether it still is.
- **The drop and the restore are visible as they happen (AUTH-06),** not only on the next glance. A level or reason change between polls raises a toast; the override cooldown is deliberately excluded from the change key, so a countdown ticking from 87s to 43s updates the badge without re-announcing itself every ten seconds.
- **Executed, failed, advisory and withheld are four outcomes, not two plus shading.** Advisory is a cyan open circle naming `would_execute`; withheld is an amber circled-slash carrying `safety_reason`. Neither is inferred from a boolean — they are rendered from the message types 02-09 created precisely so nothing has to.
- **One reason-to-text mapping, two consumers.** `grep -v '^\s*//' web/static/app.js | grep -c "watchdog"` → **1**. A command result carrying `degraded` reads identically to the badge, verified by assertion rather than by eye.
- **The badge cannot reflow its neighbours.** The header is right-anchored, so a growing badge would otherwise drag SIM / STT / DB / LLM sideways on every poll. The text has a content-independent flex basis and ellipsises, with the full string always in `title`.

## Task Commits

1. **Task 1: Add the authority indicator with its reason label** — `abf1d83` (feat)
2. **Task 2: Render advisory and withheld command results as their own states** — `fe2f0e2` (feat)
3. **Task 3: Human verification checkpoint** — no commit; auto-approved under `--auto`, no code written

## Files Created/Modified

- `web/static/index.html` (+17) — the `status-authority` indicator appended to `status-led-group`, following its siblings' structure (`status-indicator` div, `role="status"`, `aria-label`, `led` span, `status-label` span reading `AUTH`) plus a third span for the level-and-reason text. Initial text is `UNKNOWN (not polled yet)` — honest, and distinct from both the unreachable and the degraded wordings.
- `web/static/style.css` (+147) — `.led-cyan`; `.status-authority` and `.status-authority-text` with the fixed flex basis; `auth-full` / `auth-assisted` / `auth-advisory` / `auth-degraded` / `auth-unknown` / `auth-unrecognised`; `.cmd-advisory` / `.cmd-withheld` / `.cmd-detail`; `.toast-advisory` / `.toast-caution` / `.toast-info`; a narrower basis in the 1000px media query.
- `web/static/app.js` (+237/−2) — three `dom` refs; `state.lastAuthorityKey`; a `cyan` arm in `setLed`; the authority block (`AUTHORITY_REASON_TEXT`, `AUTHORITY_LEVEL_STYLE`, `hasOwn`, `authorityReasonText`, `authorityLevelText`, `authorityPhrase`, `applyAuthority`, `renderAuthority`, `renderAuthorityUnknown`); `renderAuthority(data)` in `pollStatus` and `renderAuthorityUnknown()` in its catch; `spanWithText` / `commandLabel` / `appendCommandOutcome` / `showCommandAdvisory` / `showCommandWithheld`; `toastToneClass` and the generalised `showCommandToast`; two new switch cases.

## The checkpoint: what was and was not verified

**Task 3 was auto-approved under `--auto`. No human has loaded the page and looked at the badge.** No browser was opened, no dev server was started, no sim was connected, and no Claude call was made. Nothing below should be read as visual confirmation.

**What was actually verified, and how:**

Two throwaway node harnesses extracted the self-contained blocks from `app.js` and drove them with DOM stubs — there is no test framework for `web/static/` and this plan did not introduce one. Payload shapes were copied from the real producers (`web/server.py:1506-1533` and `orchestrator/tools.py:407-442`), not from the plan's prose.

Authority badge, 11 cases:

| Case | Rendered text | Class | LED | Toast |
|---|---|---|---|---|
| full / config (first render) | `FULL (configured)` | `auth-full` | green | none |
| advisory / config | `ADVISORY (configured)` | `auth-advisory` | cyan | advisory |
| advisory / override + cooldown | `ADVISORY (pilot override, 87s left)` | `auth-advisory` | cyan | advisory |
| advisory / override, cooldown ticks | `ADVISORY (pilot override, 43s left)` | `auth-advisory` | cyan | **none** |
| advisory / watchdog | `ADVISORY (command path down)` | `auth-advisory` | cyan | advisory |
| advisory / degraded + detail | `ADVISORY (authority subsystem degraded)` | `auth-advisory auth-degraded` | **red** | failure |
| assisted / config | `ASSISTED (configured)` | `auth-assisted` | amber | caution |
| client unreachable | `UNKNOWN (MERLIN unreachable)` | `auth-unknown` | red | failure |
| advisory / `quarantined` (unknown 5th reason) | `ADVISORY (quarantined)` | `auth-advisory` | cyan | advisory |
| `supervisory` (unknown level) | `supervisory (configured)` | `auth-unrecognised` | red | failure |
| nulls (server forwards with no default) | `UNREPORTED (reason not reported)` | `auth-unrecognised` | red | failure |

Asserted from that run: degraded text ≠ unknown text; degraded class ≠ unknown class; degraded text ≠ config text; unknown reason and unknown level both verbatim; first render raises no toast; a ticking cooldown raises no toast; `degraded_detail` reaches the `title`.

Command outcomes, 6 cases: all four classes distinct, all four toast tones distinct, advisory names `GEAR_DOWN`, withheld carries `Airspeed 220 kt exceeds gear extension speed of 165 kt`, a `degraded` message reads identically to the badge, a null authority is not laundered into `configured`, and neither new class ever co-occurs with the success or failure class.

Structural checks: every class the JS applies has a CSS rule and every id it looks up exists in the HTML (15 classes, 2 ids, all present); CSS braces balanced 213/213; `index.html` div nesting balanced 26/26 with no negative depth. Wire contract re-checked against the producers: `AuthorityReason` is exactly `config` / `override` / `watchdog` / `degraded`, `AuthorityLevel` exactly `advisory` / `assisted` / `full`, and `summary()` really does emit `cooldown_remaining_s` and `degraded_detail` under those names.

**What a human still needs to do.** Start the server (`cd web && python3 run.py`, then http://localhost:3838) and walk these. The first column is the plan's step number.

| # | How to induce it | What correct looks like |
|---|---|---|
| 2 | No `AUTHORITY_LEVEL` in `.env` (defaults to `full`) | `AUTH ● FULL (configured)`, green. **Judge the layout**: it must sit with SIM / STT / DB / LLM without crowding or shifting them. This is the one claim the harness cannot make — it verified the CSS *rule* exists, not that the result looks right. |
| 3 | `AUTHORITY_LEVEL=advisory`, restart, reload | `ADVISORY (configured)`, cyan |
| 4 | At advisory, ask MERLIN "gear down" | A cyan `○` row saying `advisory, not sent` and `WOULD SEND: GEAR_DOWN` — clearly not the green tick. Confirm nothing reached the sim. |
| 5 | `AUTHORITY_LEVEL=assisted`, restart; request gear down at high speed or flaps above Vfe | An amber `⊘` row with the safety reason, distinguishable from both green success and red failure |
| 6 | `AUTHORITY_LEVEL=full`, restart; any command | Normal green executed result, unchanged |
| 7 | Stop the server with the page open; wait one poll (**10 s**, `STATUS_POLL_MS`) | Badge flips to a pulsing red `UNKNOWN (MERLIN unreachable)`. It must **not** say "degraded", and must not still say `FULL`. |
| — | Pilot override: at `full` or `assisted`, move a watched control in the sim by hand | Badge drops to `ADVISORY (pilot override, Ns left)` with a toast, then restores itself with a second toast when the cooldown lapses. This exercises AUTH-06 end to end and is the one path with live moving parts. |
| 8 | **The question this checkpoint exists to answer** | At a glance, in a dim cockpit-style display, can you tell *which* of the four reasons put MERLIN in advisory? If the answer is "I had to lean in and read it", the badge has failed AUTH-08 regardless of what the harnesses report. |

**`degraded` is deliberately not in that table**, and the plan says why: `AUTHORITY_LEVEL` is validated at `Settings` construction, so a degraded state cannot be induced from configuration without editing code. It is covered on the server by 02-09's construction-failure tests and on the client by the harness row above plus the grep criteria. It is not unverified — it is verified somewhere other than by hand.

## Decisions Made

- **Advisory is cyan, not red.** The plan asked for "attention", and the existing LED vocabulary is green / amber / red. Red for a deliberately configured advisory would read as a fault and would collide with the two states that genuinely are faults (unreachable, unrecognised). `--cyan` is already the palette's informational colour and is used for secondary text throughout, so this reuses the vocabulary rather than extending it. Amber was unavailable — it belongs to `assisted`.
- **The client-side unknown pulses; the server-reported degraded does not.** Both are red, so something has to separate them at a glance once the wording is too small to read across a cockpit. The pulse is borrowed from the existing `conn-degraded` treatment.
- **`showCommandToast`'s second parameter became a tone.** It was a boolean picking `toast-success` / `toast-failure`, and four states need four tones. Booleans still map to exactly what they mapped to before, so every pre-existing caller is unchanged.
- **The override cooldown is excluded from the transition key.** It ticks down on every poll; including it would fire a toast every ten seconds for the whole cooldown, which would train the pilot to ignore authority toasts — the opposite of AUTH-06's intent.
- **No toast on first render.** Page load is not a transition. Without this, every reload announces the current level as though it had just changed.
- **The badge text has a fixed flex basis rather than a fixed width.** `flex: 0 1 39ch` is content-independent, so text changes never reflow neighbours, while still allowing the badge to shrink on a narrow viewport — where it ellipsises rather than pushing the LED group off the header.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] `degraded` carried no fault colour, only wording**

- **Found during:** Task 1, when the harness output showed `advisory/degraded` rendering with the same cyan LED and cyan text as `advisory/config`
- **Issue:** The plan says "Set the indicator class from `authority_level`", which is correct for the three levels but leaves `degraded` visually identical to a deliberate advisory configuration. The wording distinguished them, but the transition toast that shouts about it fades after 3 seconds and the badge is what remains on screen indefinitely. Threat T-02-10-06 is specifically about a degraded state being read as a configured one, and colour is the first thing read at a glance in a dim cockpit.
- **Fix:** a `auth-degraded` modifier applied *in addition to* the level class (so the level class is still set from `authority_level`, as instructed), switching the LED and text to the fault colour. The level classification is unchanged; this only adds a fault tint on top.
- **Files modified:** `web/static/app.js`, `web/static/style.css`
- **Commit:** `abf1d83`

**Total deviations:** 1 (Rule 2)
**Impact on plan:** None on scope. Every acceptance criterion in Tasks 1 and 2 was verified as written; this strengthens the plan's own success criterion that "a degraded server and an unreachable server are never rendered the same way" by extending it to "a degraded server and a *configured* advisory are never rendered the same way either".

## Issues Encountered

- **A comment containing the word `innerHTML` broke a verification grep.** The plan's verification item counts `innerHTML` occurrences in `app.js`; my comment explaining that these strings are *not* concatenated into markup pushed the count from 8 to 9 while adding no such concatenation. Reworded to "markup". Worth recording because it is the same hazard the plan already anticipated for `grep -c` over comments, arriving from the opposite direction: a comment can fail a safety grep as easily as it can falsely satisfy a rendering one.
- **A slice-based HTML balance check produced a false alarm** (5 open / 7 close) because the slice began inside an already-open tag. Re-checked across the whole file: 26/26, depth never negative. Recorded so the false positive is not rediscovered later.
- **Plan `<verify>` blocks `cd` to the main repo path** (`/mnt/c/Users/bould/source/airdale`), as every prior plan in this phase noted. Run from the worktree root instead.
- **The worktree HEAD was behind the assigned base** (`80f22bf` vs `3a58fa9`), so the sanctioned `git reset --hard` in the startup check applied, after the branch-namespace assertion passed. Same as 02-01, 02-06, 02-08 and 02-09.

## The testing gap this plan does not close

`web/static/` has no test framework, no bundler and no build step, and this plan deliberately did not introduce one — that is an architectural decision with blast radius well beyond a badge. The consequence is real and should be stated rather than glossed:

**Nothing in CI will catch a regression in any of this.** The 91 web tests exercise `web/server.py` and never load `app.js`. The two node harnesses that verified the four-reason mapping, the verbatim fallthrough and the degraded/unreachable distinction were scratch files outside the repo; they are gone. If someone later adds a fifth `AuthorityReason` and gives it no arm, or "simplifies" `renderAuthorityUnknown` into the degraded path, the greps in this plan's acceptance criteria are the only structural guard, and greps are not run by CI either.

This is the same shape of exposure CLAUDE.md records for the voice-backend abstraction that "was silently reverted once and went undetected for four months" — and the response there was `test_voice.py`'s structural guards. The equivalent here would be a small node-based test for `web/static/`, which is a phase-scoped decision, not a plan-scoped one. Flagged for the roadmap rather than smuggled in.

## Verification

- `node --check web/static/app.js` — exits 0
- `python3 -m pytest web/tests/ -q` — **91 passed, 1 skipped** (identical to the pre-change baseline; no test added, none modified, none regressed)
- `grep -c "status-authority" web/static/index.html` — **2** (≥ 1)
- `grep -c "authority_level" web/static/app.js` — **1**; `authority_reason` — **1** (each ≥ 1)
- `grep -c "degraded_detail" web/static/app.js` — **1** (≥ 1)
- Explicit arms present for `'config'`, `'override'`, `'watchdog'`, `'degraded'` and for `'advisory'`, `'assisted'`, `'full'`; unrecognised values render verbatim (proven by the harness rows above, not only by grep)
- `grep -v '^\s*//' web/static/app.js | grep -c "watchdog"` — **1** (the mapping is defined once and shared)
- `grep -c "command_advisory" web/static/app.js` — **1**; `command_withheld` — **1**
- `grep -c "cmd-advisory" web/static/style.css` — **2**; `cmd-withheld` — **2**
- `grep -c "cmd-success\|cmd-failure" web/static/app.js` — **1**, unchanged from before Task 2
- `grep -c "innerHTML" web/static/app.js` — **8**, unchanged from the pre-plan baseline; no new occurrence, and the two new renderers use text nodes exclusively
- `style.css` has classes for all three levels plus the unknown state, and for degraded and unrecognised — 5 `auth-*` classes total
- 15 JS-applied classes and 2 looked-up ids all resolve; CSS braces 213/213; HTML divs 26/26
- `git diff --numstat 3a58fa9 HEAD` — exactly the three files in `files_modified`; no deletions in either commit; no untracked files left behind
- **Python suites and ruff were not re-run: zero `.py` files appear in this plan's diff.** The orchestrator (1302 / 2 xfailed), telemetry-service (38) and both CI-parity ruff commands were verified clean by 02-09 at this same base and cannot have been affected by three static-asset changes.

## Known Stubs

None. Every contract in the plan's `<interfaces>` block is consumed: `authority_level`, `authority_reason`, `authority.cooldown_remaining_s`, `authority.degraded_detail`, and both new message types with all their fields.

One deliberate scope boundary, named so the verifier does not read it as a stub: **`OverrideDetector.events` still has no drain.** 02-09 left the queue filling on the browser path and named the badge and the spoken restore as this plan's work. The badge half is delivered — an override drop and its restore both change `authority_reason` and therefore both raise a transition toast within one poll, which is what AUTH-06's "informs the pilot" asks for. The *spoken* announcement, which would require draining that queue into the TTS path, is not in this plan's task list, files or acceptance criteria, and was not added.

## Threat Flags

None. This plan adds no endpoint, no auth path, no file access and no schema at a trust boundary — it renders an existing read-only `GET` and two existing message types. All six `mitigate` dispositions in the plan's register are implemented:

| Threat ID | Where it is closed |
|---|---|
| T-02-10-01 | The `pollStatus` catch calls `renderAuthorityUnknown()`, which overwrites the badge rather than leaving it; harness row confirms the previous value does not survive |
| T-02-10-02 | `cmd-advisory` class, cyan `○` rather than the success tick, and `would_execute` named in the row; asserted never to co-occur with the success class |
| T-02-10-03 | `message`, `safety_reason`, `would_execute` and the reason label are attached via `textContent`; `degraded_detail` via the `title` property. `grep -c innerHTML` unchanged at 8 |
| T-02-10-04 | Level and reason changes raise a toast through the existing helper; the cooldown is excluded from the key so real transitions are not buried under repeats |
| T-02-10-05 | Display only. No control added, `/api/status` remains `GET`, and nothing in `app.js` writes an authority value |
| T-02-10-06 | `degraded` has its own arm, its own wording, its own fault colour and `degraded_detail` in the title; the mapping has no default fallthrough; the client-side unknown is a separate class, separate wording and pulses |

T-02-10-07 (rendering internal counters) remains `accept` — only `cooldown_remaining_s` and `degraded_detail` are surfaced, both where they aid interpretation. T-02-10-SC holds: no package was installed, and the frontend still has no package manager.

## Notes for the Orchestrator

- STATE.md and ROADMAP.md were **not** modified (worktree mode; the orchestrator owns those writes post-wave).
- **REQUIREMENTS.md was not modified either**, following the precedent every plan in this phase set. The honest read now that the rendering has landed:
  - **AUTH-08** — *fully delivered.* 02-09 delivered the data; this delivers the display. The level and the reason are visible without opening dev tools. Safe to mark, with the caveat that the "at a glance / legible" half rests on an auto-approved checkpoint (see below).
  - **AUTH-02** — *fully delivered.* Advisory, withheld, blocked and executed are four distinguishable outcomes on both entry points, and the browser now renders advisory and withheld as their own states rather than as a green tick.
  - **AUTH-06** — *delivered for the badge.* The drop, the rolling cooldown and the restore are all visible within one poll and announced by toast as they happen. If the requirement's acceptance text says "spoken", the TTS half is not done and belongs with whoever drains `OverrideDetector.events`.
- **The checkpoint was auto-approved, not performed.** The "What a human still needs to do" table above is the outstanding work, and step 8 — whether the reason is legible at a glance in a cockpit-style display — is the question AUTH-08 actually asks and the one no harness answered. Please surface that table to the user.
- Wave 6 — this plan touches only `web/static/*`. It does not contend with `web/server.py`, which 02-09 rewrote.
- `verify.key-links` should resolve both of this plan's links: `app.js` → `server.py /api/status` via `authority_level`, and `app.js` → the chat WebSocket via `command_advisory`. 02-09's forward-looking `server.py` → `app.js` link now resolves in both directions.

## Deferred Issues

**`web/static/` has no automated test coverage of any kind**, so none of this plan's logic is guarded by CI. Detailed under "The testing gap this plan does not close" above. The fix is a small node-based test setup for the browser assets; it is a phase-scoped decision and was not taken unilaterally here. Recorded in this summary rather than in a shared `deferred-items.md` to avoid a shared-file write from a worktree agent.

**The advisory command row keeps its cyan outcome colour even when the reason is `degraded`.** The badge tints degraded as a fault; a `command_advisory` row carrying `degraded` does not, because its class encodes the *outcome* (nothing was transmitted) rather than the authority reason, and the reason is spelled out in the row's detail span with the same wording the badge uses. This is a considered choice, not an oversight, but it is the one place where degraded is less visually loud than on the badge.

## Next Phase Readiness

Ready, with one caveat that is not a code caveat: the human verification behind Task 3 has not happened. Everything a machine can check about this plan has been checked, and the outstanding item is a judgment about legibility in a cockpit-style display, which is exactly why the plan made it a checkpoint rather than an assertion.

## Self-Check: PASSED

- Files claimed modified: all 3 present on disk with the described changes (`web/static/index.html`, `web/static/style.css`, `web/static/app.js`).
- Commits claimed: `abf1d83` and `fe2f0e2` — both present in `git log`.
- No files created, none deleted (`git diff --diff-filter=D` empty across both commits); no untracked files left behind.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-01*
