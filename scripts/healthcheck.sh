#!/usr/bin/env bash
# =============================================================================
# MERLIN v2 Health Check
# Verifies all subsystems are operational. Use for acceptance testing.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
WARN=0

check() {
    local name="$1"
    local result="$2"
    local required="$3"
    if [ "$result" = "ok" ]; then
        echo -e "  ${GREEN}PASS${NC}  $name"
        PASS=$((PASS + 1))
    elif [ "$required" = "optional" ]; then
        echo -e "  ${YELLOW}WARN${NC}  $name"
        WARN=$((WARN + 1))
    else
        echo -e "  ${RED}FAIL${NC}  $name"
        FAIL=$((FAIL + 1))
    fi
}

# Load .env
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

echo ""
echo -e "${CYAN}MERLIN v2 Health Check${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo ""

# --- API Keys ---
echo -e "${CYAN}API Keys:${NC}"
[ -n "$ANTHROPIC_API_KEY" ] && check "Anthropic API key" "ok" || check "Anthropic API key" "fail"
STT_BACKEND="${STT_BACKEND:-deepgram}"
TTS_BACKEND="${TTS_BACKEND:-cartesia}"
if [ "$STT_BACKEND" = "deepgram" ]; then
    [ -n "$DEEPGRAM_API_KEY" ] && check "Deepgram API key" "ok" || check "Deepgram API key" "fail"
else
    check "Deepgram API key (not needed, STT=$STT_BACKEND)" "ok"
fi
if [ "$TTS_BACKEND" = "cartesia" ]; then
    [ -n "$CARTESIA_API_KEY" ] && check "Cartesia API key" "ok" || check "Cartesia API key" "fail"
else
    check "Cartesia API key (not needed, TTS=$TTS_BACKEND)" "ok"
fi
echo ""

# --- Services ---
echo -e "${CYAN}Services:${NC}"
curl -sf http://localhost:3838/api/status >/dev/null 2>&1 && check "Web server (port 3838)" "ok" || check "Web server (port 3838)" "fail"
curl -sf http://localhost:8000/api/v2/heartbeat >/dev/null 2>&1 && check "ChromaDB (port 8000)" "ok" || check "ChromaDB (port 8000)" "fail"
curl -sf http://localhost:8080/api/health >/dev/null 2>&1 && check "Telemetry service (port 8080)" "ok" || check "Telemetry service (port 8080)" "fail"

if [ "$STT_BACKEND" = "whisper" ]; then
    curl -sf http://localhost:9090/health >/dev/null 2>&1 && check "Whisper STT (port 9090)" "ok" || check "Whisper STT (port 9090)" "fail"
else
    check "Whisper STT (not needed, STT=$STT_BACKEND)" "ok"
fi
echo ""

# --- Python Tests ---
echo -e "${CYAN}Test Suite:${NC}"
cd "$PROJECT_ROOT/orchestrator"
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi
TEST_OUTPUT=$(python3 -m pytest tests/ -q --tb=no 2>&1 | tail -1)
if echo "$TEST_OUTPUT" | grep -q "passed"; then
    PASSED=$(echo "$TEST_OUTPUT" | grep -oP '\d+ passed')
    check "Python tests ($PASSED)" "ok"
else
    check "Python tests: $TEST_OUTPUT" "fail"
fi
cd "$PROJECT_ROOT"
echo ""

# --- V2 Module Imports ---
echo -e "${CYAN}v2 Modules:${NC}"
python3 -c "from orchestrator.stt.deepgram import DeepgramSTTClient" 2>/dev/null && check "Deepgram STT client" "ok" || check "Deepgram STT client" "fail"
python3 -c "from orchestrator.tts.cartesia import CartesiaClient" 2>/dev/null && check "Cartesia TTS client" "ok" || check "Cartesia TTS client" "fail"
python3 -c "from orchestrator.emergency import EmergencyDetector" 2>/dev/null && check "Emergency detector" "ok" || check "Emergency detector" "fail"
python3 -c "from orchestrator.validation import ResponseValidator" 2>/dev/null && check "Response validator" "ok" || check "Response validator" "fail"
python3 -c "from orchestrator.chunking import AviationChunker" 2>/dev/null && check "Aviation chunker" "ok" || check "Aviation chunker" "fail"
python3 -c "from orchestrator.reranker import CrossEncoderReranker" 2>/dev/null && check "Cross-encoder reranker" "ok" || check "Cross-encoder reranker" "fail"
python3 -c "from orchestrator.aviation_tools import get_notams, get_weather" 2>/dev/null && check "Aviation tools" "ok" || check "Aviation tools" "fail"
echo ""

# --- Summary ---
TOTAL=$((PASS + FAIL + WARN))
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo -e "  ${GREEN}$PASS passed${NC}  ${RED}$FAIL failed${NC}  ${YELLOW}$WARN warnings${NC}  ($TOTAL total)"
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo ""

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
