#!/usr/bin/env bash
# =============================================================================
# MERLIN Shutdown Script
# Gracefully stops all MERLIN components.
# =============================================================================

CYAN='\033[0;36m'
GREEN='\033[0;32m'
NC='\033[0m'

log() { echo -e "${CYAN}[MERLIN]${NC} $1"; }
ok()  { echo -e "${GREEN}[  OK  ]${NC} $1"; }

# Stop web server
log "Stopping web server..."
lsof -ti :3838 2>/dev/null | xargs -r kill 2>/dev/null && ok "Web server stopped" || ok "Web server not running"

# Stop SimConnect bridge
log "Stopping SimConnect bridge..."
"/mnt/c/Windows/System32/taskkill.exe" /F /IM SimConnectBridge.exe >/dev/null 2>&1 && ok "Bridge stopped" || ok "Bridge not running"

# Stop Docker services
log "Stopping Docker services..."
docker compose stop whisper chromadb 2>/dev/null
ok "Docker services stopped"

echo ""
log "All MERLIN components shut down."
