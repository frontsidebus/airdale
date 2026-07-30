---
phase: 06
phase_name: "CI/CD Pipeline"
project: "MERLIN — Airdale"
generated: "2026-07-29"
counts:
  decisions: 13
  lessons: 10
  patterns: 9
  surprises: 7
missing_artifacts:
  - "06-VERIFICATION.md"
  - "06-UAT.md"
---

# Phase 06 Learnings: CI/CD Pipeline

## Decisions

### Three separate path-filtered workflows instead of one monolithic pipeline
`python-ci.yml`, `dotnet-ci.yml`, and `docker-ci.yml`, each triggering only on the paths it cares about.

**Rationale:** A PR touching only C# should not spin up Python lint, and vice versa. The plans made this a verifiable truth: "A PR touching only C# or Docker files does NOT trigger the Python CI workflow" and its mirror image.
**Source:** 06-01-PLAN.md, 06-02-PLAN.md, 06-02-SUMMARY.md

### Python CI splits into a fast job and a gated integration job
`lint-and-test` runs on every push and PR; `integration` runs with `if: github.event_name == 'pull_request'` and `needs: lint-and-test`.

**Rationale:** Docker service startup dominates the runtime. Gating it behind both a PR-only condition and a passing lint/test job means the slow job never runs when the fast one already failed.
**Source:** 06-01-PLAN.md, 06-01-SUMMARY.md

### Each workflow lists itself in its own path triggers
`.github/workflows/python-ci.yml` appears in `python-ci.yml`'s own `paths:`, and likewise for the other two.

**Rationale:** Recorded as research Pitfall 6. Without it, a PR that only edits the workflow does not run the workflow, so the change lands untested.
**Source:** 06-01-PLAN.md, 06-02-PLAN.md

### One shared ruff config for all three Python projects
`ruff check orchestrator/ telemetry-service/ web/ --config orchestrator/pyproject.toml`, and the same `--config` for `ruff format --check`.

**Rationale:** Three copies of the same ruff settings would drift. Nominating the orchestrator's config as canonical means one place defines line length, rule set, and formatting for the whole Python side.
**Source:** 06-01-PLAN.md, 06-01-SUMMARY.md

### .NET CI builds only `SimConnectBridge.Tests.csproj`, never the main project
The plan states it twice, in caps: "Do NOT reference `SimConnectBridge.csproj` anywhere in the workflow."

**Rationale:** The main project references the SimConnect SDK DLL at a Windows-specific `HintPath` that does not exist on a CI runner. The test project is self-contained — it pulls sources via `Compile Include` and carries its own `TestDataStructs.cs`.
**Source:** 06-02-SUMMARY.md, 06-02-PLAN.md

### .NET CI runs on `ubuntu-latest`, not a Windows runner
`actions/setup-dotnet@v4` with `dotnet-version: '8.0.x'` on Linux.

**Rationale:** Follows directly from the test-project-only decision. Once the SimConnect dependency is out of scope, there is no reason to pay for or wait on Windows runners.
**Source:** 06-02-PLAN.md, 06-02-SUMMARY.md

### Docker CI validates the compose config before building, and never starts containers
`docker compose config --quiet` then `docker compose build`. The plan adds a negative criterion: the file must not contain `docker compose up`.

**Rationale:** Config validation is near-instant and catches YAML errors before a multi-minute image build. Starting containers would test runtime behavior, which is the integration job's concern, not the build workflow's.
**Source:** 06-02-SUMMARY.md, 06-02-PLAN.md

### No Docker layer caching
Explicitly declined.

**Rationale:** "Dockerfile changes are infrequent enough that caching adds complexity without meaningful time savings." A deliberate non-optimization, recorded with its reasoning rather than left as an omission.
**Source:** 06-02-SUMMARY.md

### pip caching keyed across all three dependency manifests
`actions/setup-python@v5` with `cache: 'pip'` and a multi-line `cache-dependency-path` covering `orchestrator/pyproject.toml`, `telemetry-service/pyproject.toml`, and `web/requirements.txt`.

**Rationale:** A cache key derived from only one manifest goes stale silently when a sibling project's dependencies change.
**Source:** 06-01-PLAN.md, 06-01-SUMMARY.md

### The integration job uses the dev compose overlay for a `tiny` Whisper model
`docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d whisper chromadb`.

**Rationale:** Downloading `large-v3-turbo` on every integration run would dominate CI time. Phase 03 deliberately preserved the dev overlay's `tiny` override with a comment pointing at the production default — this is the payoff.
**Source:** 06-01-PLAN.md, 06-01-SUMMARY.md

### Services are health-polled before integration tests run
`timeout 120 bash -c 'until curl -sf http://localhost:9090/health; do sleep 5; done'` for Whisper, and a 30s equivalent against ChromaDB's `/api/v1/heartbeat`.

**Rationale:** `docker compose up -d` returns as soon as containers start, not when they are ready to serve. Whisper needs to load a model first. The differing budgets (120s vs 30s) reflect that asymmetry.
**Source:** 06-01-PLAN.md

### Teardown is unconditional via `if: always()`
`docker compose down` runs whether the integration tests pass or fail.

**Rationale:** A failing test must not leak containers into the runner's state or a self-hosted environment.
**Source:** 06-01-PLAN.md

### Web's editable install was skipped and the web test step made conditional
The plan called for `cd web && pip install -e ".[dev]"`; the workflow installs only `pip install -r web/requirements.txt`, and the web test step is guarded by a `hashFiles` check.

**Rationale:** Recorded as "web has no pyproject.toml" and "web/tests/ may not exist yet." Both premises were false at the time — see Lessons and Surprises.
**Source:** 06-01-SUMMARY.md

---

## Lessons

### For the third time in this milestone, an executor built on a false premise about a prior phase's output
Plan 06-01 recorded a Rule 3 blocking deviation stating "web has no pyproject.toml," and separately guarded the web test step because "`web/tests/` may not exist yet." Phase 05 plan 01 created `web/pyproject.toml`, `web/tests/__init__.py`, `web/tests/conftest.py`, and `web/tests/test_rest.py` — completing at `2026-03-28T19:16:34Z`, roughly three hours before plan 06-01 started at `22:14:57Z`. `web/pyproject.toml` is listed in plan 06-01's own `<context>` block and in Task 1's `read_first`.

**Context:** The same failure mode as plan 03-02 ("Plan 01 implemented sync httpx.Client") and plan 05-01 ("web/server.py uses module-level globals without FastAPI dependency injection"). Three separate phases, three Rule 3 blocking deviations, each asserting something an already-committed artifact contradicts. Unlike Phase 05's, this one had a downstream cost — the milestone needed `8587ba5 fix: unblock python CI + close out v1.2 (#71)`.
**Source:** 06-01-SUMMARY.md, 05-01-SUMMARY.md, 06-01-PLAN.md

### A conditional test step can produce a green CI run that tested nothing
Guarding the web test step on `hashFiles` means that if the guard's assumption is wrong — or the path expression does not match — the step is skipped, not failed, and the job still reports success.

**Context:** The web test suite (34 tests) had just been written in Phase 05 specifically so CI could enforce it. A `hashFiles` guard is appropriate for genuinely optional work; for a suite that is supposed to exist, its absence should fail the build.
**Source:** 06-01-SUMMARY.md, 05-02-SUMMARY.md

### A workflow that does not list itself in its `paths:` filter ships untested
The first PR editing the workflow will not run it.

**Context:** Caught in research as Pitfall 6 and applied to all three workflows. Cheap to include, and the failure mode is invisible — everything looks fine because nothing ran.
**Source:** 06-01-PLAN.md, 06-02-PLAN.md

### A platform-SDK reference in one project can be isolated by targeting only its sibling test project
`SimConnectBridge.csproj` cannot build on Linux; `SimConnectBridge.Tests.csproj` can, because it uses `Compile Include` on the sources it needs plus its own `TestDataStructs.cs`.

**Context:** Turned a "this needs Windows runners" problem into a one-line path change. Worth checking for this shape before accepting a platform constraint on CI.
**Source:** 06-02-SUMMARY.md, 06-02-PLAN.md

### Order cheap validation before expensive work
`docker compose config --quiet` before `docker compose build` means a YAML typo fails in seconds rather than after image layers have been pulled and built.

**Context:** Stated as its own decision: "Compose config validation before build catches YAML syntax errors early, before a slow image build."
**Source:** 06-02-SUMMARY.md

### `docker compose up -d` returning is not the same as services being ready
Both Whisper and ChromaDB needed explicit health polling before tests could run, with Whisper needing four times the budget because it loads a model at startup.

**Context:** Without the poll, integration tests race container startup and fail intermittently — the worst kind of CI failure.
**Source:** 06-01-PLAN.md

### CI health checks must use the host-mapped port, not the container port
The Whisper poll targets `http://localhost:9090/health`, matching the compose port mapping.

**Context:** Flagged as research Pitfall 3. Easy to get wrong by copying the internal port from the service definition.
**Source:** 06-01-PLAN.md

### YAML validity is locally verifiable; workflow correctness is not
Both plans verified with `python3 -c "import yaml; yaml.safe_load(...)"` plus grep assertions on step contents. Neither could establish that the workflow actually passes.

**Context:** Plan 06-01's own readiness note says it plainly: "Python CI workflow ready; will trigger on next PR touching Python files." The first real feedback arrives after merge — which is where the false web premise surfaced.
**Source:** 06-01-PLAN.md, 06-02-PLAN.md, 06-01-SUMMARY.md

### Path-filtered workflows need their filters checked for mutual exclusivity
Plan 06-02's verification block includes "Path filters are mutually exclusive from Python CI (no overlap)" as an explicit check.

**Context:** Overlapping filters mean two workflows run the same checks on the same PR — wasted minutes and duplicated status entries. Checking exclusivity across workflow files is easy to forget because each file looks correct in isolation.
**Source:** 06-02-PLAN.md

### Negative grep assertions are how you enforce "never reference X"
`! grep "SimConnectBridge.csproj" ... | grep -v Tests` and "File does NOT contain `docker compose up`" turn prohibitions into automated checks.

**Context:** Same technique Phase 02 used to prove ElevenLabs code was fully extracted. A rule stated only in prose is a rule that will be broken by the next edit.
**Source:** 06-02-PLAN.md

---

## Patterns

### One workflow per tech stack, each path-filtered to its own tree
Python, .NET, and Docker each get a file whose `paths:` covers only its directories plus itself.

**When to use:** Polyglot monorepos. Keeps PR status checks proportional to what actually changed and makes each workflow independently readable.
**Source:** 06-01-SUMMARY.md, 06-02-SUMMARY.md (`patterns-established`)

### Self-referencing path trigger
Include the workflow's own file path in its `paths:` list.

**When to use:** Always, on every path-filtered workflow. Non-negotiable — it is the only way workflow edits get exercised before merge.
**Source:** 06-01-PLAN.md, 06-02-PLAN.md

### Two-tier job gating with `needs:` plus an event condition
`lint-and-test` on every event; `integration` with both `needs: lint-and-test` and `if: github.event_name == 'pull_request'`.

**When to use:** Any pipeline with a fast check and a slow, resource-hungry one. The two conditions cover different concerns — don't waste the expensive job on a broken build, and don't run it on every push to a branch.
**Source:** 06-01-PLAN.md, 06-01-SUMMARY.md (`patterns-established`)

### Health-gate bash loop with a hard timeout
`timeout <N> bash -c 'until curl -sf <url>; do sleep <M>; done'`, with N sized to the service's real startup cost.

**When to use:** Before any test step that depends on a container started earlier in the job. Budget per service rather than using one global number.
**Source:** 06-01-PLAN.md

### `if: always()` on teardown steps
Cleanup runs regardless of upstream step outcome.

**When to use:** Every step that releases a resource — containers, temp registries, cloud fixtures.
**Source:** 06-01-PLAN.md

### Shared lint config across sibling projects via `--config`
Point every project's lint invocation at one canonical `pyproject.toml`.

**When to use:** Monorepos with multiple Python packages that should share style. One file to change, no drift.
**Source:** 06-01-PLAN.md, 06-01-SUMMARY.md

### Validate-then-build step ordering
Cheap syntactic validation first, expensive materialization second.

**When to use:** Docker builds, Terraform plans, schema migrations — anywhere a fast parse can pre-empt a slow apply.
**Source:** 06-02-SUMMARY.md

### Negative acceptance criteria on forbidden strings
Assert the absence of `SimConnectBridge.csproj` (un-suffixed) and of `docker compose up`.

**When to use:** Whenever a plan's core constraint is "never do X." Pairs with the same technique used for extraction refactors in Phase 02.
**Source:** 06-02-PLAN.md

### Local parse plus content greps as the verify command for config files
`yaml.safe_load()` for validity, then greps for each required step and each forbidden string.

**When to use:** CI configs, compose files, and other declarative artifacts that cannot be executed in the authoring environment. It is the strongest check available locally — and worth pairing with a note that real verification happens on the first PR.
**Source:** 06-01-PLAN.md, 06-02-PLAN.md

---

## Surprises

### The CI phase was written believing the test suite from the previous phase might not exist
Phase 06 exists because of an explicit roadmap decision: "CI/CD is final phase because tests must exist before CI can enforce them." Its Python workflow then skipped the web editable install and wrapped the web test step in an existence guard.

**Impact:** The phase-ordering rationale was undermined by the phase it was designed to protect. `web/pyproject.toml` was in plan 06-01's context block; it had existed for three hours; the summary records it as absent.
**Source:** 06-01-SUMMARY.md, 05-01-SUMMARY.md, .planning/STATE.md

### Python CI required a follow-up commit to unblock it
`8587ba5 fix: unblock python CI + close out v1.2 (#71)` — the milestone could not close until the pipeline this phase delivered was repaired.

**Impact:** The only phase in v1.2 whose deliverable is known to have needed post-hoc fixing before the milestone shipped, and the cost traces directly to the false web-dependency premise.
**Source:** git log, 06-01-SUMMARY.md

### Both plans record byte-identical start and completion timestamps
`06-01-SUMMARY.md` and `06-02-SUMMARY.md` both report `Started: 2026-03-28T22:14:57Z` and `Completed: 2026-03-28T22:15:40Z` — one task in the first, two in the second, 43 seconds total for three workflow files.

**Impact:** The two plans were genuinely independent (both `wave: 1`, both `depends_on: []`) so parallel execution is plausible, but identical second-resolution timestamps mean the metrics cannot be trusted for per-plan attribution.
**Source:** 06-01-SUMMARY.md, 06-02-SUMMARY.md

### The dependency graph contradicts itself between frontmatter fields
Plan 06-01 declares `depends_on: []` and `wave: 1` while also declaring `affects: [06-02-PLAN]`. Plan 06-02 likewise declares `wave: 1`, `depends_on: []`.

**Impact:** Either the `affects` edge is spurious or the wave assignment is. As written, two plans in the same wave claim an ordering relationship — harmless here since neither touches the other's files, but the graph is not internally consistent.
**Source:** 06-01-SUMMARY.md, 06-02-PLAN.md

### Declining an optimization was recorded as a first-class decision
"No Docker layer caching -- Dockerfile changes are infrequent, caching adds complexity without meaningful time savings" appears in `key-decisions` alongside the things that were built.

**Impact:** Notably better artifact hygiene than the milestone's average. A future reader considering adding caching finds the prior reasoning instead of assuming it was overlooked.
**Source:** 06-02-SUMMARY.md

### The phase's artifacts exist only inside the milestone archive
`.planning/phases/06-ci-cd-pipeline/` does not exist; the plans, summaries, context, and research live solely under `.planning/milestones/v1.2-phases/06-ci-cd-pipeline/`. Both plan files still reference `@.planning/phases/06-ci-cd-pipeline/06-CONTEXT.md`.

**Impact:** Phase 06 is the only v1.2 phase fully archived out of the active tree, so its plans' own `@`-references now point at paths that do not resolve. Phases 01–05 were left in place, giving the milestone a half-archived state.
**Source:** 06-01-PLAN.md, 06-02-PLAN.md, filesystem layout

### The phase whose entire purpose is automated verification was never itself verified
No `06-VERIFICATION.md`, no `06-UAT.md`. Coverage of CICD-01 through CICD-07 rests on the two plan summaries.

**Impact:** Third consecutive phase (04, 05, 06) shipped without a verification report. Given that the one phase in v1.2 that *was* independently verified (Phase 03) turned up four blockers a green test suite had missed, the gap is a pattern rather than an oversight — and Phase 06's needed-unblocking outcome is what an independent verifier existed to catch.
**Source:** 06-01-SUMMARY.md, 06-02-SUMMARY.md, 03-VERIFICATION.md
