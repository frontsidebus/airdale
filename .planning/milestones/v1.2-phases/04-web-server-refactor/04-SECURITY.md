---
phase: 04-web-server-refactor
audited: "2026-04-16"
asvs_level: 1
auditor: gsd-secure-phase
result: SECURED
threats_open: 0
threats_total: 4
---

# Phase 04 Security Audit — Web Server Refactor

## Summary

All 4 threats in the threat register are CLOSED. No open threats. No unregistered flags.

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-04-01 | Tampering | mitigate | CLOSED | web/server.py:179,265 — AppState created once in lifespan, assigned to app.state.app_state; get_app_state (line 118) and get_ws_app_state (line 123) both read from app.state — no per-request copies |
| T-04-02 | Denial of Service | mitigate | CLOSED | web/server.py:272-283 — lifespan teardown calls sim_client.disconnect(), tts_client.aclose(), whisper_client.aclose(), deepgram_client.aclose(), cartesia_client.aclose() all guarded by None/is_closed checks |
| T-04-03 | Denial of Service | mitigate | CLOSED | web/server.py:1269 (whisper_client None check in _transcribe_with_confidence), 348 (get_status None guard), 493 (tts_client None guard in text_to_speech), 1226 (_send_tts_chunk_rest None guard); tts_client is unconditionally initialized at line 253 so is never None when ElevenLabs path is active |
| T-04-04 | Information Disclosure | mitigate | CLOSED | web/server.py:377 — elevenlabs_configured emits bool() coercion of API key, not the key value; no route handler returns raw settings fields, API keys, or credentials in response bodies |

## Unregistered Flags

None. No threat flags were recorded in SUMMARY.md for this phase beyond the threat register above.

## Accepted Risks Log

None. No threats were accepted in this phase.

## Notes

- The `settings` object is stored on `AppState` (line 103) and accessible within the server process. This is the same exposure as the previous module-level globals and is within the accepted design for a single-process local application. API keys travel only outbound (in Authorization/xi-api-key headers to ElevenLabs/Cartesia/Deepgram) and are not reflected in any response body.
- The CORS policy at lines 297-303 (`allow_origins=["*"]`) is a pre-existing design decision for local LAN use and is outside this phase's scope.
