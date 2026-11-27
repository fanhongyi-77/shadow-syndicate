#!/usr/bin/env bash
# Start the VOID ECHO Phase 0.3 MCP Echo Server on localhost only.
#
#   ./scripts/serve.sh                      # http://127.0.0.1:8765/mcp
#   VOID_ECHO_JSON_RESPONSE=1 ./scripts/serve.sh   # non-streaming JSON responses
#   VOID_ECHO_ALLOW_ANY_HOST=1 ./scripts/serve.sh  # required for OpenAI Secure MCP Tunnel
set -euo pipefail
cd "$(dirname "$0")/.."

export VOID_ECHO_HOST="${VOID_ECHO_HOST:-127.0.0.1}"
export VOID_ECHO_PORT="${VOID_ECHO_PORT:-8765}"
export VOID_ECHO_PATH="${VOID_ECHO_PATH:-/mcp}"

if [[ "$VOID_ECHO_HOST" != "127.0.0.1" && "$VOID_ECHO_HOST" != "localhost" ]]; then
  echo "refusing to bind non-loopback host: $VOID_ECHO_HOST" >&2
  exit 1
fi

# Deterministic launch: the editable-install .pth is unreliable across uv rebuilds,
# so put src/ on PYTHONPATH and run the module directly.
exec env PYTHONPATH=src .venv/bin/python -m void_echo_test.server
