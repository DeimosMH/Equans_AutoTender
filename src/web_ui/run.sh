#!/bin/sh
# Start the AutoTender web UI (backend + page).
# Usage: ./run.sh [port]     - default port 8080
exec python3 "$(dirname "$0")/server.py" "${1:-8080}"
