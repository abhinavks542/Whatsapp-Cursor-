#!/usr/bin/env bash
set -euo pipefail

PORT=8000
HEARTBEAT_URL="http://localhost:${PORT}/api/v2/heartbeat"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${PROJECT_ROOT}/.chroma_server.pid"
LOG_FILE="${PROJECT_ROOT}/.chroma_server.log"

installed_packages=()
already_installed=()
server_pid=""

# Check dependencies and install only packages that pip cannot find.
if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 is required but was not found on PATH." >&2
    exit 1
fi

for package in chromadb sentence-transformers; do
    if python3 -m pip show "$package" >/dev/null 2>&1; then
        already_installed+=("$package")
        echo "$package is already installed."
    else
        installed_packages+=("$package")
    fi
done

if ((${#installed_packages[@]} > 0)); then
    echo "Installing missing package(s): ${installed_packages[*]}"
    python3 -m pip install "${installed_packages[@]}"
fi

# Require the tools used for port detection and health checks.
for utility in lsof curl; do
    if ! command -v "$utility" >/dev/null 2>&1; then
        echo "Error: ${utility} is required but was not found on PATH." >&2
        exit 1
    fi
done

# If anything owns the port, reuse it only when its Chroma heartbeat is healthy.
listener_info="$(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"
if [[ -n "$listener_info" ]]; then
    server_pid="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
    if curl --silent --fail --max-time 2 "$HEARTBEAT_URL" >/dev/null; then
        echo "Chroma is already healthy on port ${PORT} (PID: ${server_pid:-unknown})."
    else
        echo "Warning: port ${PORT} is occupied by PID ${server_pid:-unknown}, but its heartbeat is not Chroma." >&2
        echo "Free the port or choose a different port before running setup again." >&2
        exit 1
    fi
else
    # Find Chroma's console script even when Python's scripts directory is not on PATH.
    chroma_command="$(command -v chroma || true)"
    if [[ -z "$chroma_command" ]]; then
        scripts_dir="$(python3 -c 'import sysconfig; print(sysconfig.get_path("scripts"))')"
        for candidate in "${scripts_dir}/chroma" "${scripts_dir}/chroma.exe"; do
            if [[ -x "$candidate" ]]; then
                chroma_command="$candidate"
                break
            fi
        done
    fi
    if [[ -z "$chroma_command" ]]; then
        echo "Error: chroma was not found after installing dependencies." >&2
        echo "Check that the Python scripts directory is available." >&2
        exit 1
    fi

    # nohup and backgrounding let setup return while Chroma keeps running.
    cd "$PROJECT_ROOT"
    nohup "$chroma_command" run --path ./chroma_data --port "$PORT" \
        >"$LOG_FILE" 2>&1 </dev/null &
    server_pid=$!
    printf '%s\n' "$server_pid" > "$PID_FILE"

    # Wait for Chroma's HTTP endpoint instead of assuming startup succeeded.
    healthy=false
    for attempt in {1..10}; do
        if curl --silent --fail --max-time 2 "$HEARTBEAT_URL" >/dev/null; then
            healthy=true
            break
        fi
        if ((attempt < 10)); then
            sleep 2
        fi
    done

    if [[ "$healthy" != true ]]; then
        echo "Error: Chroma did not become healthy after 10 checks." >&2
        if kill -0 "$server_pid" 2>/dev/null; then
            kill -TERM "$server_pid" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
        echo "Check the server log: ${LOG_FILE}" >&2
        exit 1
    fi
fi

# Summarize dependency state and the port available to the other scripts.
echo "Installed in this run: ${installed_packages[*]:-none}"
echo "Already installed: ${already_installed[*]:-none}"
echo "Server: running; PID: ${server_pid:-unknown}; port: ${PORT}"
echo "Endpoint: ${HEARTBEAT_URL}"
