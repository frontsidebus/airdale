#!/usr/bin/env bash
# =============================================================================
# MERLIN v2 Startup Script
# Starts all components: Docker services, MSFS adapter, and web server.
# Run from WSL: ./scripts/start.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# --- Parse flags ---------------------------------------------------------------
MOCK_MODE=false
for arg in "$@"; do
    case "$arg" in
        --mock) MOCK_MODE=true ;;
        *) echo "Unknown option: $arg"; exit 1 ;;
    esac
done

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()  { echo -e "${CYAN}[MERLIN]${NC} $1"; }
ok()   { echo -e "${GREEN}[  OK  ]${NC} $1"; }
warn() { echo -e "${YELLOW}[ WARN ]${NC} $1"; }
fail() { echo -e "${RED}[ FAIL ]${NC} $1"; }

# Load .env if it exists
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
fi

# Detect docker command (WSL2 may need docker.exe)
if command -v docker &>/dev/null; then
    DOCKER=docker
elif command -v docker.exe &>/dev/null; then
    DOCKER=docker.exe
else
    warn "Docker not found — ChromaDB and legacy Whisper will be unavailable"
    DOCKER=""
fi

cd "$PROJECT_ROOT"
mkdir -p "$PROJECT_ROOT/logs"

# --- 0. Pre-flight: check required API keys ---------------------------------
log "Pre-flight checks..."

STT_BACKEND="${STT_BACKEND:-deepgram}"
TTS_BACKEND="${TTS_BACKEND:-cartesia}"

PREFLIGHT_OK=true

if [ "$STT_BACKEND" = "deepgram" ] && [ -z "$DEEPGRAM_API_KEY" ]; then
    fail "DEEPGRAM_API_KEY not set (required for STT_BACKEND=deepgram)"
    warn "  Set it in .env or export it, or set STT_BACKEND=whisper for local fallback"
    PREFLIGHT_OK=false
fi

if [ "$TTS_BACKEND" = "cartesia" ] && [ -z "$CARTESIA_API_KEY" ]; then
    fail "CARTESIA_API_KEY not set (required for TTS_BACKEND=cartesia)"
    warn "  Set it in .env or export it, or set TTS_BACKEND=elevenlabs or TTS_BACKEND=local"
    PREFLIGHT_OK=false
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    fail "ANTHROPIC_API_KEY not set (required)"
    PREFLIGHT_OK=false
fi

if [ "$PREFLIGHT_OK" = false ]; then
    echo ""
    fail "Pre-flight failed. Fix the above and try again."
    exit 1
fi

ok "API keys configured (STT: $STT_BACKEND, TTS: $TTS_BACKEND)"

# --- 1. Docker services (ChromaDB + optional Whisper) ------------------------
if [ -n "$DOCKER" ]; then
    log "Starting Docker services..."

    # ChromaDB is always needed (RAG store)
    $DOCKER compose up -d chromadb telemetry-service 2>/dev/null

    # Whisper only if using legacy STT backend
    if [ "$STT_BACKEND" = "whisper" ]; then
        log "Starting Whisper container (STT_BACKEND=whisper)..."
        $DOCKER compose up -d whisper 2>/dev/null

        log "Waiting for Whisper to load model..."
        for i in $(seq 1 60); do
            status=$($DOCKER inspect merlin-whisper --format '{{.State.Health.Status}}' 2>/dev/null || echo "unknown")
            if [ "$status" = "healthy" ]; then
                ok "Whisper STT ready"
                break
            fi
            if [ "$i" -eq 60 ]; then
                warn "Whisper still loading — continuing anyway"
            fi
            sleep 5
        done
    else
        ok "Skipping Whisper (using $STT_BACKEND cloud STT)"
    fi

    # Check ChromaDB
    for i in $(seq 1 15); do
        if curl -sf http://localhost:8000/api/v2/heartbeat >/dev/null 2>&1; then
            ok "ChromaDB ready"
            break
        fi
        if [ "$i" -eq 15 ]; then
            warn "ChromaDB not responding yet — it should come up shortly"
        fi
        sleep 2
    done

    # Check Telemetry Service
    for i in $(seq 1 10); do
        if curl -sf http://localhost:8080/api/health >/dev/null 2>&1; then
            ok "Telemetry service ready"
            break
        fi
        if [ "$i" -eq 10 ]; then
            warn "Telemetry service not responding yet — it should come up shortly"
        fi
        sleep 2
    done
else
    warn "Skipping Docker services (docker not available)"
fi

# --- 2. Adapter (real MSFS or mock) ------------------------------------------
if [ "$MOCK_MODE" = true ]; then
    log "Starting mock adapter..."

    # Kill any lingering mock adapter
    pkill -f "tools/mock_adapter.py" 2>/dev/null || true
    sleep 1

    # Activate venv if available (mock adapter needs websockets)
    if [ -f "$PROJECT_ROOT/orchestrator/.venv/bin/activate" ]; then
        source "$PROJECT_ROOT/orchestrator/.venv/bin/activate"
    fi

    python3 "$PROJECT_ROOT/tools/mock_adapter.py" > "$PROJECT_ROOT/logs/mock_adapter.log" 2>&1 &
    MOCK_PID=$!
    echo "$MOCK_PID" > "$PROJECT_ROOT/logs/mock_adapter.pid"

    # Wait for the mock adapter to register with the telemetry service
    log "Waiting for mock adapter to register..."
    for i in $(seq 1 20); do
        HEALTH=$(curl -sf http://localhost:8080/api/health 2>/dev/null || echo "")
        if echo "$HEALTH" | grep -q '"adapters":1'; then
            ok "Mock adapter registered (PID: $MOCK_PID, log: logs/mock_adapter.log)"
            break
        fi
        if [ "$i" -eq 20 ]; then
            warn "Mock adapter did not register in time — check logs/mock_adapter.log"
        fi
        sleep 1
    done
else
    log "Starting MSFS adapter..."

    # Kill any existing adapter instances
    "/mnt/c/Windows/System32/taskkill.exe" /F /IM SimConnectBridge.exe >/dev/null 2>&1 || true
    sleep 1

    # Build and start in background
    ADAPTER_DIR="$PROJECT_ROOT/adapters/msfs"
    if [ -d "$ADAPTER_DIR" ]; then
        cd "$ADAPTER_DIR"
        "/mnt/c/Program Files/dotnet/dotnet.exe" build --verbosity quiet 2>/dev/null
        "/mnt/c/Program Files/dotnet/dotnet.exe" run > "$PROJECT_ROOT/logs/adapter.log" 2>&1 &
        ADAPTER_PID=$!
        cd "$PROJECT_ROOT"

        sleep 3
        if kill -0 $ADAPTER_PID 2>/dev/null; then
            ok "MSFS adapter started (PID: $ADAPTER_PID, log: logs/adapter.log)"
        else
            warn "MSFS adapter may have failed — check logs/adapter.log (is MSFS running?)"
        fi
    else
        warn "MSFS adapter directory not found at $ADAPTER_DIR"
    fi
fi

# --- 3. Web server (FastAPI) ------------------------------------------------
log "Starting MERLIN web server..."

# Kill any existing web server
lsof -ti :3838 2>/dev/null | xargs -r kill -9 2>/dev/null || true
sleep 1

# Activate venv and start
cd "$PROJECT_ROOT/web"
if [ -f "$PROJECT_ROOT/orchestrator/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/orchestrator/.venv/bin/activate"
fi
python run.py > "$PROJECT_ROOT/logs/web.log" 2>&1 &
WEB_PID=$!
cd "$PROJECT_ROOT"

# Wait for web server to be ready
for i in $(seq 1 15); do
    if curl -sf http://localhost:3838/api/status >/dev/null 2>&1; then
        ok "Web server ready on http://localhost:3838"
        break
    fi
    if [ "$i" -eq 15 ]; then
        warn "Web server slow to start — check logs/web.log"
    fi
    sleep 2
done

# --- Summary ----------------------------------------------------------------
echo ""
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
if [ "$MOCK_MODE" = true ]; then
    echo -e "${CYAN}  MERLIN AI Co-Pilot v2.0 — ${YELLOW}MOCK MODE${CYAN}${NC}"
else
    echo -e "${CYAN}  MERLIN AI Co-Pilot v2.0 — All Systems Go${NC}"
fi
echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
echo ""

# Check status
STATUS=$(curl -s http://localhost:3838/api/status 2>/dev/null)
if [ -n "$STATUS" ]; then
    SIM=$(echo "$STATUS" | python3 -c "import sys,json; print('CONNECTED' if json.load(sys.stdin).get('sim_connected') else 'WAITING')" 2>/dev/null || echo "?")
    CHROMA=$(echo "$STATUS" | python3 -c "import sys,json; print('OK' if json.load(sys.stdin).get('chromadb_available') else 'DOWN')" 2>/dev/null || echo "?")

    echo -e "  Cockpit UI:   ${GREEN}http://localhost:3838${NC}"
    echo -e "  SimConnect:   ${SIM}"
    echo -e "  STT Backend:  ${GREEN}${STT_BACKEND}${NC}"
    echo -e "  TTS Backend:  ${GREEN}${TTS_BACKEND}${NC}"
    echo -e "  ChromaDB:     ${CHROMA}"
else
    echo -e "  Cockpit UI:   http://localhost:3838"
    echo -e "  (status check failed — server may still be starting)"
fi

echo ""
echo -e "  Logs:  tail -f logs/web.log"
if [ "$MOCK_MODE" = true ]; then
    echo -e "         tail -f logs/mock_adapter.log"
else
    echo -e "         tail -f logs/adapter.log"
fi
echo ""
echo -e "  Stop:  ${CYAN}./scripts/stop.sh${NC}"
echo ""
