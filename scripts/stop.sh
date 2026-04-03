#!/usr/bin/env bash
# =============================================================================
# MERLIN v2 Shutdown Script
# Gracefully stops all MERLIN components.
# =============================================================================

CYAN='\033[0;36m'
GREEN='\033[0;32m'
NC='\033[0m'

log() { echo -e "${CYAN}[MERLIN]${NC} $1"; }
ok()  { echo -e "${GREEN}[  OK  ]${NC} $1"; }

# Detect docker command (WSL2 may need docker.exe)
if command -v docker &>/dev/null; then
    DOCKER=docker
elif command -v docker.exe &>/dev/null; then
    DOCKER=docker.exe
else
    DOCKER=""
fi

# Stop web server
log "Stopping web server..."
lsof -ti :3838 2>/dev/null | xargs -r kill 2>/dev/null && ok "Web server stopped" || ok "Web server not running"

# Stop MSFS adapter
log "Stopping MSFS adapter..."
"/mnt/c/Windows/System32/taskkill.exe" /F /IM SimConnectBridge.exe >/dev/null 2>&1 && ok "Adapter stopped" || ok "Adapter not running"

# Stop Docker services
if [ -n "$DOCKER" ]; then
    log "Stopping Docker services..."
    # Stop all MERLIN containers (ChromaDB, telemetry-service, and Whisper if running)
    $DOCKER compose stop chromadb telemetry-service whisper 2>/dev/null
    ok "Docker services stopped"
else
    log "Docker not available — skipping container shutdown"
fi

echo ""
log "All MERLIN components shut down."
