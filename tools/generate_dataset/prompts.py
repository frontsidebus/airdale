"""System prompt builder for conversation generation.

Loads the real MERLIN persona and phase styles to construct system prompts
identical to what the orchestrator uses at runtime.
"""

from __future__ import annotations

from pathlib import Path

# Project root
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PROMPTS_DIR = _PROJECT_ROOT / "data" / "prompts"

# Phase-specific response style directives (matches claude_client.py _PHASE_STYLE)
PHASE_STYLES: dict[str, str] = {
    "PREFLIGHT": "Relaxed tone, moderate length. Humor welcome—share a story if it fits. This is bonding time.",
    "TAXI": "Professional but relaxed. Concise—1-2 sentences unless asked for more. Light humor okay.",
    "TAKEOFF": "ULTRA-BRIEF. Callouts only. No filler. No humor. Every syllable matters.",
    "CLIMB": "Professional, moderate length. Light humor once established in climb. Good time for brief teaching.",
    "CRUISE": "Conversational, can be more detailed. Good time for teaching, war stories, and thorough explanations. Full MERLIN personality.",
    "DESCENT": "Briefing mode. Structured and clear. Minimal humor. Set up the approach.",
    "APPROACH": "ULTRA-BRIEF. Concise callouts only. No humor. Precise and procedural.",
    "LANDING": "ULTRA-BRIEF. Callouts only. Crisp and precise. Zero filler.",
    "LANDED": "Relaxed debrief mode. Humor welcome. Critique with warmth. 'The Navy way.'",
}

# Response pacing rules (appended last for priority)
RESPONSE_PACING = """--- RESPONSE PACING (CRITICAL) ---
- Acknowledgments & simple answers: 1-2 sentences MAX.
- Callouts (altitude, speed, gear): Short. No markdown. "Positive rate. Gear up."
- Procedures & checklists: Present 3-5 items then STOP. Wait for "check" or "continue."
- Briefings: Bullet points, not prose. Structured and scannable.
- Teaching moments (cruise only): 4-5 sentences max. Conversational, not lecture.
- Emergency: Numbered steps. No embellishment. One instruction at a time.
After asking a question: STOP. Do not answer your own question.
After a key callout: STOP. Let the Captain acknowledge.
After delivering a checklist group: STOP. Wait for "check" or "continue."
Never give unsolicited speeches."""


def load_merlin_persona() -> str:
    """Load the MERLIN system prompt from data/prompts/merlin_system.md."""
    path = _PROMPTS_DIR / "merlin_system.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    # Fallback minimal persona
    return (
        "You are MERLIN, an AI co-pilot for flight simulators. "
        "Former Navy Test Pilot. Address the pilot as 'Captain'. "
        "Be concise, professional, and use dry humor when appropriate."
    )


def load_emergency_prompt() -> str:
    """Load the emergency override prompt from data/prompts/merlin_emergency.md."""
    path = _PROMPTS_DIR / "merlin_emergency.md"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def build_system_prompt(
    phase: str,
    aircraft_name: str,
    telemetry_summary: str,
    pilot_level: str = "private",
    weather_summary: str = "",
    is_emergency: bool = False,
    diversity_seed: int = 0,
) -> str:
    """Build a complete system prompt for conversation generation.

    Args:
        phase: Flight phase string (e.g. "CRUISE")
        aircraft_name: Full aircraft name
        telemetry_summary: One-line telemetry summary
        pilot_level: Pilot skill level
        weather_summary: Weather conditions string
        is_emergency: Whether this is an emergency scenario
        diversity_seed: Seed for varying response style
    """
    parts: list[str] = []

    # Core persona
    if is_emergency:
        emergency = load_emergency_prompt()
        if emergency:
            parts.append(emergency)
        else:
            parts.append(load_merlin_persona())
    else:
        parts.append(load_merlin_persona())

    # Phase style
    style = PHASE_STYLES.get(phase, "")
    if style:
        parts.append(f"\n--- CURRENT RESPONSE STYLE ---\n{style}")

    # Flight state
    parts.append(f"\n--- CURRENT FLIGHT STATE ---\n{telemetry_summary}")
    parts.append(f"Aircraft: {aircraft_name}")

    if weather_summary:
        parts.append(f"Weather: {weather_summary}")

    # Pilot skill context
    skill_notes = {
        "student": "The Captain is a student pilot. Explain terminology. Be patient and encouraging.",
        "private": "The Captain is a private pilot. Solid basics, may need guidance on advanced topics.",
        "instrument": "The Captain is instrument-rated. Comfortable with procedures and technical detail.",
        "ATP": "The Captain is ATP-rated. Experienced professional. Keep it peer-level and efficient.",
    }
    if pilot_level in skill_notes:
        parts.append(f"\nPilot context: {skill_notes[pilot_level]}")

    # Response pacing
    parts.append(f"\n{RESPONSE_PACING}")

    # Diversity directive (varies phrasing across generations)
    verbosity = ["terse", "moderate", "natural", "detailed"][diversity_seed % 4]
    parts.append(
        f"\nTRAINING NOTE: Vary your phrasing naturally. "
        f"For this conversation, lean toward {verbosity} responses."
    )

    return "\n".join(parts)


def format_telemetry_summary(sim_state: dict) -> str:
    """Format a sim state dict into a one-line telemetry summary."""
    pos = sim_state.get("position", {})
    speeds = sim_state.get("speeds", {})
    att = sim_state.get("attitude", {})

    alt = pos.get("altitude_msl", 0)
    agl = pos.get("altitude_agl", 0)
    ias = speeds.get("indicated_airspeed", 0)
    gs = speeds.get("ground_speed", 0)
    vs = speeds.get("vertical_speed", 0)
    hdg = att.get("heading_magnetic", 0)

    parts = [f"ALT {alt:.0f}ft MSL ({agl:.0f} AGL)"]
    parts.append(f"IAS {ias:.0f}kt")
    parts.append(f"GS {gs:.0f}kt")
    parts.append(f"HDG {hdg:.0f}°")
    parts.append(f"VS {vs:+.0f}fpm")

    return " | ".join(parts)
