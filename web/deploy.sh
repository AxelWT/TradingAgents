#!/bin/bash
# Local Docker deployment helper for TradingAgents web.
# Builds and runs the single-container (backend + served frontend) stack.
set -euo pipefail

cd "$(dirname "$0")"

COMPOSE_FILE="docker-compose.local.yml"
export WEB_PORT="${WEB_PORT:-8004}"
HEALTH_URL="http://localhost:${WEB_PORT}/health"

ROOT_ENV="../.env"
BACKEND_ENV="backend/.env"

log()  { echo "[deploy] $*"; }
err()  { echo "[deploy] ERROR: $*" >&2; }

# Resolve compose v2 (plugin) vs legacy standalone binary.
detect_compose() {
    if docker compose version >/dev/null 2>&1; then
        COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then
        COMPOSE=(docker-compose)
    else
        err "Neither 'docker compose' nor 'docker-compose' found. Install Docker first."
        exit 1
    fi
}

check_docker_daemon() {
    if ! docker info >/dev/null 2>&1; then
        err "Docker daemon not running. Start Docker Desktop / dockerd first."
        exit 1
    fi
}

# Verify required env files exist before any build/up action.
check_env_files() {
    local missing=0
    if [ ! -f "$ROOT_ENV" ]; then
        err "Missing $ROOT_ENV (LLM keys). Copy .env.example -> .env and fill in keys."
        missing=1
    fi
    if [ ! -f "$BACKEND_ENV" ]; then
        err "Missing $BACKEND_ENV (DB/SMTP/admin). Copy backend/.env.example -> backend/.env and fill in."
        missing=1
    fi
    if [ "$missing" -ne 0 ]; then
        exit 1
    fi
}

compose() { "${COMPOSE[@]}" -f "$COMPOSE_FILE" "$@"; }

wait_healthy() {
    log "Waiting for service to become healthy at $HEALTH_URL ..."
    local i
    for i in $(seq 1 30); do
        if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
            log "Service is up."
            log "  web:     http://localhost:${WEB_PORT}"
            log "  api:     http://localhost:${WEB_PORT}/api"
            log "  health:  $HEALTH_URL"
            return 0
        fi
        sleep 1
    done
    err "Service did not become healthy within 30s. Check logs: $0 logs"
    return 1
}

cmd_build()    { detect_compose; check_docker_daemon; check_env_files; log "Building image..."; compose build; }

cmd_up()        { detect_compose; check_docker_daemon; check_env_files;
                  log "Starting (build if needed)..."; compose up -d --build; wait_healthy; }

cmd_start()     { cmd_up; }

cmd_rebuild()   { detect_compose; check_docker_daemon; check_env_files;
                  log "Rebuilding and restarting..."; compose up -d --build; wait_healthy; }

cmd_down()      { detect_compose; check_docker_daemon; log "Stopping & removing container..."; compose down; }

cmd_stop()      { cmd_down; }

cmd_restart()   { detect_compose; check_docker_daemon; log "Restarting..."; compose restart; }

cmd_logs()      { detect_compose; compose logs -f --tail=200; }

cmd_status()    { detect_compose; compose ps; }

cmd_shell()     { detect_compose; compose exec tradingagents bash || compose exec tradingagents sh; }

cmd_clean()     {
    detect_compose; check_docker_daemon
    echo "[deploy] WARNING: this removes the container AND the data volume (DB, reports, etc.)."
    read -r -p "[deploy] Type 'yes' to confirm: " ans
    if [ "$ans" != "yes" ]; then
        log "Aborted."
        exit 0
    fi
    log "Removing container and volume..."
    compose down -v
    log "Done. Data wiped."
}

usage() {
    cat <<EOF
TradingAgents local Docker deployment.

Usage: $0 <command>

Commands:
  build       Build the image without starting
  up          Build (if needed) and start in background, then health-check
  start       Alias of 'up'
  rebuild     Force rebuild and restart
  down        Stop and remove the container (keeps data volume)
  stop        Alias of 'down'
  restart     Restart the container
  logs        Follow container logs
  status      Show container status
  shell       Open a shell inside the running container
  clean       Remove container AND data volume (DESTROYS the DB; asks confirmation)

Env overrides:
  WEB_PORT    Host port to expose (default 8004)
EOF
}

case "${1:-}" in
    build)    cmd_build ;;
    up)       cmd_up ;;
    start)    cmd_start ;;
    rebuild)  cmd_rebuild ;;
    down)     cmd_down ;;
    stop)     cmd_stop ;;
    restart)  cmd_restart ;;
    logs)     cmd_logs ;;
    status)   cmd_status ;;
    shell)    cmd_shell ;;
    clean)    cmd_clean ;;
    ""|-h|--help|help) usage ;;
    *) err "Unknown command: $1"; usage; exit 1 ;;
esac
