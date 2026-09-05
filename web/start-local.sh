#!/bin/bash
set -uo pipefail

cd "$(dirname "$0")"

BACKEND_DIR="backend"
FRONTEND_DIR="frontend"
VENV_UVICORN="../../.venv/bin/uvicorn"
REPO_ROOT="$(cd .. && pwd)"

BACKEND_PID=""
FRONTEND_PID=""
CLEANING_UP=""

TARGET="${1:-all}"

log() { echo "[start-local.sh] $*"; }

# Start a service so that $! is the PID of the actual service process
# (we `exec` inside the subshell, replacing it with the service binary),
# while its stdout/stderr are piped through a prefixer via process
# substitution. The prefixer dies on its own when the service exits
# (EOF on the pipe), so killing $PID is sufficient to stop everything.
start_backend() {
    log "Starting backend on :8000 ..."
    (
        cd "$BACKEND_DIR"
        export PYTHONPATH="$(pwd)"
        exec "$VENV_UVICORN" app.main:app \
            --host 0.0.0.0 --port 8000 --reload --log-level info \
            --reload-dir "$REPO_ROOT/web/$BACKEND_DIR" \
            --reload-dir "$REPO_ROOT/tradingagents"
    ) > >(sed -u 's/^/[backend] /') 2>&1 &
    BACKEND_PID=$!
}

start_frontend() {
    log "Starting frontend on :5173 ..."
    (
        cd "$FRONTEND_DIR"
        exec ./node_modules/.bin/vite
    ) > >(sed -u 's/^/[frontend] /') 2>&1 &
    FRONTEND_PID=$!
}

cleanup() {
    # Guard against re-entrancy (EXIT fires after INT/TERM handler).
    [ -n "$CLEANING_UP" ] && return
    CLEANING_UP=1
    trap - INT TERM EXIT
    local killer=$1
    echo
    log "$killer received, shutting down..."
    local pids=()
    [ -n "$BACKEND_PID" ]   && kill -0 "$BACKEND_PID"   2>/dev/null && pids+=("$BACKEND_PID")
    [ -n "$FRONTEND_PID" ] && kill -0 "$FRONTEND_PID" 2>/dev/null && pids+=("$FRONTEND_PID")
    if [ ${#pids[@]} -gt 0 ]; then
        kill "${pids[@]}" 2>/dev/null
        log "sent SIGTERM to: ${pids[*]}"
        # Give children a moment to exit gracefully, then force kill.
        local i alive
        for i in 1 2 3 4 5 6 7 8 9 10; do
            alive=0
            local pid
            for pid in "${pids[@]}"; do
                kill -0 "$pid" 2>/dev/null && alive=1
            done
            [ "$alive" -eq 0 ] && break
            sleep 0.3
        done
        for pid in "${pids[@]}"; do
            kill -9 "$pid" 2>/dev/null
        done
    fi
    wait 2>/dev/null
    log "done."
    exit 0
}

# Start a single service and wait until it exits.
start_and_wait() {
    local start_fn=$1 name=$2 pid
    trap 'cleanup INT' INT
    trap 'cleanup TERM' TERM
    "$start_fn"
    if [ "$name" = "backend" ]; then pid="$BACKEND_PID"; else pid="$FRONTEND_PID"; fi
    log "$name running (pid=$pid). Press Ctrl+C to stop."
    while kill -0 "$pid" 2>/dev/null; do
        sleep 0.5
    done
    log "$name exited."
    cleanup EXIT
}

case "$TARGET" in
    backend)
        start_and_wait start_backend backend
        ;;
    frontend)
        start_and_wait start_frontend frontend
        ;;
    all|"")
        trap 'cleanup INT' INT
        trap 'cleanup TERM' TERM
        trap 'cleanup EXIT' EXIT
        start_backend
        start_frontend
        log "Both services up: backend=$BACKEND_PID frontend=$FRONTEND_PID"
        log "  frontend: http://localhost:5173"
        log "  backend:  http://localhost:8000/api"
        log "Press Ctrl+C to stop both."

        # Poll: as soon as either child dies, stop the other.
        while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
            sleep 0.5
        done

        if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
            log "backend exited unexpectedly, stopping frontend..."
        else
            log "frontend exited unexpectedly, stopping backend..."
        fi
        cleanup EXIT
        ;;
    *)
        cat <<EOF
Usage: $0 [backend|frontend]
  (no args)  start both backend (:8000) and frontend (:5173)
  backend    start backend only
  frontend   start frontend only
EOF
        exit 1
        ;;
esac
