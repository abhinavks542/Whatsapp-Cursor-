#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${PROJECT_ROOT}/.chroma_server.pid"
PORT=8000

if [[ ! -f "$PID_FILE" ]]; then
    echo "No Chroma PID file found at ${PID_FILE}; no process was stopped."
    exit 0
fi

read -r server_pid < "$PID_FILE"
if [[ ! "$server_pid" =~ ^[0-9]+$ ]]; then
    echo "Error: PID file does not contain a valid process ID: ${PID_FILE}" >&2
    exit 1
fi

if ! kill -0 "$server_pid" 2>/dev/null; then
    echo "Recorded Chroma process ${server_pid} is not running; removing stale PID file."
    rm -f "$PID_FILE"
    exit 0
fi

# Refuse to signal a reused or unrelated PID.
process_command="$(ps -p "$server_pid" -o args= 2>/dev/null || true)"
if [[ "$process_command" != *chroma*run*--port*"$PORT"* ]]; then
    echo "Error: PID ${server_pid} is not the expected Chroma run process; refusing to stop it." >&2
    exit 1
fi

echo "Sending TERM to Chroma process ${server_pid}."
kill -TERM "$server_pid"

# Allow Chroma to shut down cleanly; leave the PID file if it does not exit.
for attempt in {1..10}; do
    if ! kill -0 "$server_pid" 2>/dev/null; then
        rm -f "$PID_FILE"
        echo "Chroma process ${server_pid} stopped."
        exit 0
    fi
    sleep 1
done

echo "Warning: Chroma process ${server_pid} is still running; PID file was kept." >&2
exit 1