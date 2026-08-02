---
phase: 02-authority-safety-layer
plan: 16
subsystem: docs
tags: [documentation, requirements-ledger, test-counts, non-goal-reconciliation, gap-closure]

# Dependency graph
requires:
  - phase: 02-authority-safety-layer
    provides: "the five gap-closure plans whose landed code these two documents now describe (02-11 through 02-15)"
  - phase: 02-authority-safety-layer
    provides: "02-VERIFICATION.md's Requirements Coverage table and its three gaps, which set the evidence bar each checked box had to clear"
provides:
  - "CLAUDE.md test counts measured at the close of Phase 2, with the C# suite excluded rather than estimated"
  - "CLAUDE.md decision 26 naming the transmission predicate, the undo pop ordering, the three-system refusal table and both announcement consumers"
  - "CLAUDE.md decision 22 recording that the pre-execution guard grew to 13 rules and why"
  - "A Phase 2 requirement ledger where every checked box cites the plan and artefact that earned it"
  - "A written reconciliation of the 'no new envelope rules' non-goal with the six rules 02-14 added"
affects: [phase-02 re-verification, phase-03 planning (reads the ledger), any agent loading CLAUDE.md as project instructions]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Test counts in documentation are measured at write time and dated; a suite that cannot be run is excluded from the total rather than carried forward stale"
    - "A requirement checkbox carries its evidence inline — plan plus artefact — so a reader can tell an unfinished requirement from an unrecorded one"
    - "A residual finding that does not bear on the requirement text is recorded on the line rather than silently absorbed into the tick"

key-files:
  created:
    - .planning/phases/02-authority-safety-layer/02-16-SUMMARY.md
  modified:
    - CLAUDE.md
    - .planning/REQUIREMENTS.md
    - docs/ARCHITECTURE.md
    - docs/VOICE_PIPELINE.md

key-decisions:
  - "No C# test count is asserted. `dotnet` is not installed in this environment, so the headline figure is 1,538 *Python* tests across three suites and the C# project is named as excluded-and-unmeasured. Carrying the old 'plus the C# adapter test project' phrasing into a total would have implied a verification that did not happen."
  - "The two `human_verification:` items are recorded as **approved**, never as observed or confirmed. The developer replied `approved` with no narrative for step 9 or step 10; 02-15 recorded that distinction deliberately and this plan preserves it verbatim on AUTH-08's ledger line."
  - "All ten of AUTH-01..08, CMD-07 and CMD-08 were judged earned. AUTH-03 and AUTH-05 carry their open residuals (WR-10 part 2, WR-05) on the line rather than being left unchecked, because neither residual contradicts the requirement as written — one concerns telemetry freshness, the other reconnect suppression."
  - "The Coverage rollup table was updated even though it sits outside the Phase 2 section: ticking ten boxes while leaving 'AUTH | 8 | 0 | 8' would have authored a fresh self-contradiction into the ledger this plan exists to make trustworthy. Recorded as a Rule 2 deviation."
  - "The stale retroactive-ratio prose ('35 of the 42') was left alone and reported instead. Both its numbers were already wrong before this plan (measured: 27 retroactive lines, 43 done pre-change); correcting figures I had not audited the provenance of would be the exact failure mode this phase exists to fix."
  - "The non-goal reconciliation states the boundary narrowly — 'a phase that widens the write surface owns the rules for what it widened' — and explicitly warns against 'resolving' the contradiction by deleting the six rules."

patterns-established:
  - "Documentation that describes a guard names the code symbol, so a future reader can grep from prose to implementation (`_was_transmitted`, `drain_authority_events`, `_authority_event_pump`, `UNCONFIRMABLE_REFUSED_ACTIONS`, `MAX_PENDING_ANNOUNCEMENTS`)"
  - "A ledger citation that names two plans when a requirement 'read as complete while shipping a live hazard' (CMD-07 + 02-14), so the history is not lost in the tick"

requirements-completed: [AUTH-01, AUTH-02, AUTH-03, AUTH-04, AUTH-05, AUTH-06, AUTH-07, AUTH-08, CMD-07, CMD-08]

# Metrics
duration: 22min
completed: 2026-08-02
---

# Phase 02 Plan 16: Making the Documents Agree With the Code Summary

**CLAUDE.md now carries test counts measured this session rather than inherited (1,389 orchestrator / 111 web / 38 telemetry-service, with the C# suite named as unmeasured instead of estimated), decision 26 describes the authority subsystem the five gap-closure plans actually shipped, and every Phase 2 requirement box states what earned it — including the two whose evidence is a blanket approval rather than an observation.**

## Performance

- **Duration:** ~22 min
- **Tasks:** 2 (both `type="auto"`, one commit each)
- **Files modified:** 4 (2 planned, 2 approved scope addition)
- **Commits:** 2 task commits + this summary

## Accomplishments

### Task 1 — CLAUDE.md counts and the authority narrative

- **Counts measured, not derived.** Every figure written down was printed by a suite run
  on the base commit in this session:

  | Suite | Command | Result |
  |---|---|---|
  | orchestrator | `cd orchestrator && python3 -m pytest -q` | `1389 passed, 2 xfailed` |
  | web | `cd web && python3 -m pytest -q` | `111 passed, 1 skipped` |
  | telemetry-service | `cd telemetry-service && python3 -m pytest -q` | `38 passed` |

  Headline is now **1,538 Python tests**, dated 2026-08-02. The stale
  `~1,395 tests passing` / `1,302 orchestrator, 55 web` bullet is gone (IN-01). The web
  figure had drifted furthest — CLAUDE.md claimed 55 against a measured 111.

- **The C# suite is excluded, and says so.** `dotnet` is not installed here
  (`command -v dotnet` → not found), so `cd adapters/msfs && dotnet test` could not run.
  The bullet states that plainly and tells a reader to run it on a machine with the
  .NET 8 SDK before trusting any C# coverage claim. Plan 02-14 flagged the same
  limitation for the phase verifier; this carries it forward rather than quietly
  reinstating a number.

- **Test categories extended**, keeping every existing entry: the `_was_transmitted`
  predicate and the false-confirmation regressions it pins, the bounded announcement
  queue and both consumers, the CLI authority status formatter, the parking-brake
  refusal, and the fuel / mixture / crossfeed / parking-brake rules.

- **Decision 22** gained one clause: the pre-execution guard now covers the fuel
  selector, mixture, crossfeed and parking brake alongside gear, flaps, AP master and
  throttle (`DEFAULT_RULES` 7 → 13, confirmed by importing the module and counting), and
  it grew because CMD-07 made eight previously-NACKing events reachable — a rule set
  that does not track the reachable surface is a guard in name only.

- **Decision 26** gained the four facts it was missing, written into the narrative
  rather than appended: the single transmission predicate and why both halves are
  load-bearing; the undo path popping only after the reversal is on the wire, with the
  past-tense "Reversed GEAR_DOWN" failure it replaces; the three-system refusal table
  with `parking_brake` named as the only reachable one; and the announcement queue with
  exactly one consumer per process, including *why* it is called out — the queue shipped
  dead and three executors each declined to mark AUTH-06 for it.

- **Decision numbering unchanged**; 26 is still the last, and the directory listing was
  not touched.

### Task 2 — The requirement ledger and the non-goal

All ten in-scope boxes were checked, each with an inline citation naming the plan and
the artefact or test:

| Req | Verdict | Evidence cited |
|---|---|---|
| AUTH-01 | checked | 02-01/04/05/08 — `AuthorityState`, the gate, the `send_command` floor |
| AUTH-02 | checked | 02-04 + **02-11** (`_was_transmitted`, gated `safety_note`, undo ordering) + **02-12** (browser mirror) |
| AUTH-03 | checked | 02-04 + 02-11 (`no_verdict` withhold) + 02-14 (crossfeed warning) |
| AUTH-04 | checked | 02-04 branch unchanged; **02-14** is what makes "unless blocked" non-vacuous |
| AUTH-05 | checked | 02-06 — `COMMAND_WATCHED_FIELDS`, `recent_dispatches()` attribution |
| AUTH-06 | checked | 02-06 drop + **02-13** (`drain_authority_events`) + **02-15** (`_authority_event_pump`) |
| AUTH-07 | checked | 02-05/08 stop half; **02-13** closed the CLI "says so" gap (WR-07) |
| AUTH-08 | checked | 02-09/02-10 + 02-15 badge-at-announcement; human_verification noted as *approved* |
| CMD-07 | checked | 02-02 **and 02-14 together** — see below |
| CMD-08 | checked | 02-04 + **02-14** extension to `parking_brake` |
| CMD-09 | **unchecked** | deferral honoured; sequencing sentence byte-identical |
| VARC-06 | untouched | already checked before this plan |

- **CMD-07 cites both plans deliberately.** It read as SATISFIED at verification while
  shipping a live hazard: it turned `FUEL_SELECTOR_OFF` and `CROSS_FEED_*` into real
  `TransmitClientEvent` calls with no rule behind them at a default `AUTHORITY_LEVEL` of
  `full`. The citation keeps both halves so "satisfied" is not read as "was safe on
  arrival".

- **Residuals recorded on the line, not absorbed into the tick.** AUTH-03 carries WR-10
  part 2 (a verdict computed from *stale* telemetry is still treated as live) marked
  "Residual, not scored", with the reasoning that the requirement text concerns severity
  rather than freshness. AUTH-05 carries WR-05 (reconnect can register as a false
  override) the same way.

- **The two `human_verification:` items are reported as approved.** AUTH-08's line states
  that the live-browser legibility and perceived-timing checks were **approved** by a
  blanket developer `approved` and were *not* narrated as observations, pointing at
  `02-15-SUMMARY.md`. The words "observed" and "confirmed" appear nowhere near them.

- **The non-goal is reconciled in writing.** The paragraph keeps "no new envelope rules"
  verbatim and adds a dated qualification block: the six rules 02-14 added, why CMD-07 is
  the reason the reachable surface widened, `MAGNETO_SET` as the precedent held back for
  the identical hazard, the boundary drawn narrowly (**a phase that widens the write
  surface owns the rules for what it widened**), the outstanding broader `SAFE-*` pass
  with `deice` named as the one reachable-and-unruled system, and an explicit warning not
  to "resolve" the contradiction by deleting the rules.

## Task Commits

| # | Task | Commit | Type |
|---|---|---|---|
| 1 | CLAUDE.md counts, categories, decision 22, decision 26, + the two doc-drift lines | `8cbb261` | docs |
| 2 | Phase 2 requirement ledger with evidence, non-goal qualification, Coverage rollup | `dcbf15e` | docs |

## Files Created/Modified

- `CLAUDE.md` — counts bullet rewritten with measured figures and the C# exclusion;
  Test categories extended; decision 22 gained the guard-coverage clause; decision 26
  gained four woven-in facts naming `_was_transmitted`, `UNCONFIRMABLE_POSITION_SYSTEMS`,
  `UNCONFIRMABLE_REFUSED_ACTIONS`, `MAX_PENDING_ANNOUNCEMENTS`, `drain_authority_events`
  and `_authority_event_pump`.
- `.planning/REQUIREMENTS.md` — ten Phase 2 boxes checked with inline citations; the
  non-goals paragraph qualified; the Coverage table's CMD, AUTH and Total rows brought
  into line with the boxes.
- `docs/ARCHITECTURE.md` (line 142) and `docs/VOICE_PIPELINE.md` (line 416) — the
  residual `safety_note` drift, see Deviations.

## Deviations from Plan

### Auto-fixed / approved-scope

**1. [Approved scope addition] The two residual `safety_note` doc-drift lines**

- **Found during:** Task 1 (flagged in the task brief as an approved addition; originally
  reported by 02-11's executor and again by 02-14's, which corrected the two files inside
  its own scope and named these two as unreachable).
- **Issue:** 02-11 gated `safety_note` on `_was_transmitted(result)`, so it is no longer
  unconditional for critical commands. `docs/ARCHITECTURE.md:142` and
  `docs/VOICE_PIPELINE.md:416` still described it as unconditional, and both sat outside
  every plan's `files_modified`.
- **Fix:** One clause each, stating the note is attached only when the command actually
  reached the adapter and was acknowledged — a command refused by the authority gate,
  NACKed, or timed out carries no `safety_note`.
- **Files modified:** `docs/ARCHITECTURE.md`, `docs/VOICE_PIPELINE.md`
- **Committed in:** `8cbb261`

**2. [Rule 2 - Missing critical functionality] Coverage rollup table updated**

- **Found during:** Task 2
- **Issue:** The plan says not to touch sections outside Phase 2 and the non-goals
  paragraph. But ticking ten boxes while the Coverage table still read
  `AUTH (Phase 2) | 8 | 0 | 8` and `CMD | 9 | 6 | 3` would have *authored* a fresh
  self-contradiction into the ledger — the precise defect this plan exists to remove,
  one section further down the same file.
- **Fix:** CMD `9 | 8 | 1`, AUTH `8 | 8 | 0`, Total `67 | 53 | 14`. Arithmetic checked
  both ways: the eleven group rows sum to 67 total, 53 done, 14 open.
- **Files modified:** `.planning/REQUIREMENTS.md`
- **Committed in:** `dcbf15e`

---

**Total deviations:** 2 (1 approved scope addition, 1 Rule 2). No Rule 4 situations arose.
**Impact on plan:** No requirement ID added, removed or renumbered; no code touched; no
`STATE.md` or `ROADMAP.md` write.

## Reported, Not Fixed

**The retroactive-ratio prose in the Coverage section is stale, and I left it that way
deliberately.** Line 212 reads *"35 of the 42 completed requirements are retroactive"*.
Both numbers were already wrong before this plan: the file contains **27** lines matching
`- [x] **XXX-NN** (retroactive)`, and the Coverage table said 43 done, not 42. I did not
correct them because I have not audited where 35 and 42 came from, and writing a
confident number I had not established is the exact failure mode this phase exists to
correct. It needs someone to decide whether "retroactive" means the marker or something
broader, then set both figures from a count. Flagged for the re-verification pass.

## Decisions Made

Captured in the frontmatter `key-decisions`. The two load-bearing ones:

**No C# count is asserted anywhere.** The old bullet said "plus the C# adapter test
project", which invited a reader to treat the headline as covering it. With `dotnet`
absent I could either drop the phrase and leave the omission silent, or name the
exclusion. Naming it is the only version that does not quietly imply a verification that
did not happen — and it tells the next reader exactly what to run.

**"Approved" is not "observed".** 02-15's executor recorded that the developer typed
`approved` and supplied no narrative for the ffmpeg-absent voice degradation or the badge
legibility and perceived timing. That distinction survives into AUTH-08's ledger line
verbatim. A blanket approval closes a gate; it does not manufacture evidence, and a
ledger that launders one into the other is worse than an unchecked box.

## Verification

| Check | Command | Result |
|---|---|---|
| Orchestrator suite | `cd orchestrator && python3 -m pytest -q` | `1389 passed, 2 xfailed` — matches the figure written into CLAUDE.md |
| Web suite | `cd web && python3 -m pytest -q` | `111 passed, 1 skipped` — matches |
| Telemetry-service suite | `cd telemetry-service && python3 -m pytest -q` | `38 passed` — matches |
| C# adapter suite | `cd adapters/msfs && dotnet test` | **NOT RUN** — `command -v dotnet` reports not installed. No count asserted, in CLAUDE.md or here. |
| CI-parity lint | `ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml --extend-ignore ...` | `All checks passed!` |
| CI-parity format | `ruff format --check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml` | `111 files already formatted` |
| Task 1 gate | `grep -q drain_authority_events && grep -q _was_transmitted && ! grep -q "~1,395 tests passing"` | passes |
| Task 2 gate | `grep -q "\[ \] \*\*CMD-09\*\*" && grep -q "\[x\] \*\*AUTH-06\*\*"` | passes |
| CMD-09 deferral intact | `grep -rn "MAGNETO_SET\|TOGGLE_STARTER1" adapters/msfs/SimConnectManager.cs` | no output |
| Rules count | `python3 -c "... len(DEFAULT_RULES)"` | `13` — matches decision 22's claim |
| Files changed vs. base | `git diff --name-only 58701c4 HEAD` | `.planning/REQUIREMENTS.md`, `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/VOICE_PIPELINE.md` — the two planned plus the two approved |

**Task 1 acceptance criteria:** `~1,395 tests passing` → 0 matches; `55 web` → 0 matches;
`_was_transmitted` → 3; `drain_authority_events` → 1; `_authority_event_pump` → 1;
`UNCONFIRMABLE_REFUSED_ACTIONS` → 1; `MAX_PENDING_ANNOUNCEMENTS` → 1; decision 22 names
all four new systems; last numbered decision is still 26.

**Task 2 acceptance criteria:** `- [x] **AUTH-02**` and `- [x] **AUTH-06**` both present
with gap-closure parentheticals; every checked AUTH/CMD box names at least one plan file;
`CMD-09` still `- [ ]` and its line is absent from the diff entirely (the only diff line
mentioning CMD-09 is the new non-goals prose); `VARC-06` absent from the diff;
`grep -c "^\- \[.\] \*\*"` reports **68** before and after.

## Known Stubs

None. Both files are prose; no placeholder, no unwired path, no TODO/FIXME introduced.

## Threat Flags

None. This plan changed four Markdown files and no source. Every `mitigate` disposition in
the plan's register holds: T-02-16-01 (each checked box carries a plan-and-artefact
citation, and residuals are stated rather than hidden), T-02-16-02 (all three counts
measured this session; the unmeasurable fourth is named as such), T-02-16-03 (the non-goal
contradiction is written down and reconciled, naming CMD-07 and `MAGNETO_SET`), T-02-16-04
(CMD-09 unchecked, its sequencing sentence untouched — confirmed absent from the diff),
T-02-16-05 (no executable behaviour altered). T-02-16-SC holds: no package-manager command
was run.

## User Setup Required

None.

## Next Phase Readiness

- **The ledger is now a usable signal for Phase 3 planning.** AUTH-01…08, CMD-07 and
  CMD-08 are checked with evidence; CMD-09 and EVAL-07 are the open items a Phase 3
  planner will meet first. MNVR-04 ("maneuvers respect the Phase 2 authority level and
  abort on pilot override") depends on AUTH-01/05/06, all three now recorded as delivered.
- **Two things a re-verification should re-derive rather than inherit from me:** the
  C# adapter suite (unmeasurable here) and the retroactive-ratio prose flagged above.
- **The `human_verification:` items remain approved, not observed.** If a later phase
  needs the announcement-latency judgement specifically — for instance to decide whether
  the announcement path must beat the 10 s poll by a wider margin — it needs a fresh
  observation, not a citation of the approval.
- **Deliberately not written:** `.planning/STATE.md` (including its
  "Requirement coverage: 42 of 63" line, now further out of date) and `.planning/ROADMAP.md`
  — both orchestrator-owned, per the plan's `<notes>`. `02-VERIFICATION.md` is untouched so
  the before-and-after stays legible; a plan must not grade its own phase.
- **Still open across the phase, unchanged by this plan:** WR-02, WR-03, WR-04, WR-05,
  WR-08, WR-09, WR-10 part 2, WR-11, WR-12, IN-02, IN-03, IN-05, and the four-layer
  `parking_brake` position fix that D-02 deferred for carb heat and fuel pump.

## Self-Check: PASSED

Verified on `worktree-agent-a770bf219f308cd64`, based on `58701c4`:

- **Files present:** `CLAUDE.md`, `.planning/REQUIREMENTS.md`, `docs/ARCHITECTURE.md`,
  `docs/VOICE_PIPELINE.md`, this summary — all five confirmed on disk.
- **Commits present:** `8cbb261`, `dcbf15e`, `9b135f2`.
- **No deletions** anywhere in the plan — `git diff --diff-filter=D --name-only 58701c4 HEAD`
  is empty.
- **`git diff --name-only 58701c4 HEAD`** lists exactly those five files.
  `.planning/STATE.md` and `.planning/ROADMAP.md` are **not** among them.
- **No untracked files left behind**; working tree clean.
- **No source file touched** — the diff is Markdown only, which is why the Python
  suites and CI-parity lint are unaffected by this plan.

---
*Phase: 02-authority-safety-layer*
*Completed: 2026-08-02*
