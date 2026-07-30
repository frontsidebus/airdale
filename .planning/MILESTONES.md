# Milestones

Historical record of shipped MERLIN versions.

---

## v1.2 — Consolidation & Quality

**Shipped:** 2026-04-18
**Phases:** 6 (1-6)
**Plans:** 14
**Tasks:** ~26 (aggregated across plans)
**Timeline:** 2026-03-26 → 2026-04-18

### Delivered

Consolidation milestone that eliminated technical debt from rapid v1.0/v1.1 development: removed deprecated config, fixed race conditions, pinned Docker images, wired the existing TTS/Whisper abstractions into all consumers, refactored the web server to FastAPI DI, added web server test coverage, and stood up GitHub Actions CI/CD. All 36 v1 requirements shipped.

### Key Accomplishments

1. **TTS integration** — Web server and CLI voice module both use `TTSClient` protocol with persistent connections; ElevenLabs WebSocket streaming; Kokoro selectable via config; phrase cache hits pre-generated audio
2. **Whisper consolidation** — Three divergent transcription implementations replaced by a single async `WhisperClient`; model upgraded from `medium` → `large-v3-turbo`
3. **Web server DI refactor** — `AppState` dataclass (11 fields) replaces module-level globals; every handler accesses shared state through `Depends(get_app_state)`; identical barge-in behavior preserved
4. **Web server test coverage** — Chat WebSocket round-trip, barge-in cancellation, TTS streaming, transcription, phrase cache, telemetry proxy, status endpoint — all tested
5. **CI/CD pipeline** — GitHub Actions runs ruff + pytest (orchestrator, telemetry-service, web), dotnet test (MSFS adapter), and Docker compose build verification on every PR; path-based filtering prevents cross-language CI runs; failures block merge

### Known Deferred Items

Captured at milestone close on 2026-04-18:

- **Phase 03 VERIFICATION.md formal re-run** — The 4 FAIL items found during initial verification were fixed in subsequent work and annotated with file:line evidence under `## Post-hoc Resolution`, but VERIFICATION.md itself retains the `gaps_found` marker (tooling reads status markers, not prose). Acknowledged as acceptable; a formal re-verification pass would be paperwork.
- **web/server.py early-boot module state** — Tests monkeypatch globals instead of using DI overrides because server.py retains some module-level state for early-boot logging. Functionally fine; worth revisiting if the logging infra changes.

### Git Reference

- First milestone commit (requirements defined): `2026-03-26`
- Close-out PR: `#71 — fix: unblock python CI + close out v1.2` (`8587ba5`)
- Final annotation: `docs(phase-03): annotate resolved FAILs in VERIFICATION` (`a62c52e`)

---
