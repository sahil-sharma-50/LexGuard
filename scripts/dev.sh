#!/usr/bin/env bash
# Start (or stop) all Lexguard local services in one terminal.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="${REPO_ROOT}/.dev.pids"
LOG_DIR="${REPO_ROOT}/.dev-logs"
MCP_PORT="${MCP_PORT:-8010}"
API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

NPM_GLOBAL_BIN="$(npm prefix -g 2>/dev/null)/bin"
if [ -x "${NPM_GLOBAL_BIN}/pnpm" ]; then
  export PATH="${NPM_GLOBAL_BIN}:${PATH}"
fi

stop_services() {
  if [ ! -f "${PID_FILE}" ]; then
    echo "No running dev services recorded (${PID_FILE} missing)."
    return 0
  fi
  echo "Stopping dev services..."
  while read -r pid name; do
    if kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
      echo "  stopped ${name} (pid ${pid})"
    fi
  done < "${PID_FILE}"
  rm -f "${PID_FILE}"
  wait 2>/dev/null || true
  echo "All dev services stopped."
}

if [ "${1:-}" = "stop" ]; then
  stop_services
  exit 0
fi

if [ -f "${PID_FILE}" ]; then
  echo "Dev services may already be running. Run 'make stop' first." >&2
  exit 1
fi

if [ ! -f "${REPO_ROOT}/.env" ]; then
  echo "Missing .env. Run 'make setup' or 'cp .env.example .env'" >&2
  exit 1
fi

if [ ! -x "${REPO_ROOT}/agent/.venv/bin/lexguard" ]; then
  echo "Agent venv missing. Run 'make setup'" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source "${REPO_ROOT}/.env"
set +a

mkdir -p "${LOG_DIR}"
: > "${PID_FILE}"

cleanup() {
  stop_services
}
trap cleanup EXIT INT TERM

start_service() {
  local name="$1"
  shift
  local log_file="${LOG_DIR}/${name}.log"
  echo "Starting ${name} (log: ${log_file})"
  "$@" >"${log_file}" 2>&1 &
  echo "$! ${name}" >> "${PID_FILE}"
}

start_service mcp \
  bash -lc "cd '${REPO_ROOT}/alpaca-mcp-server-main' && \
    ALPACA_API_KEY='${ALPACA_API_KEY}' ALPACA_SECRET_KEY='${ALPACA_SECRET_KEY}' ALPACA_PAPER_TRADE=true \
    uv run alpaca-mcp-server --transport streamable-http --port ${MCP_PORT}"

start_service serve \
  bash -lc "cd '${REPO_ROOT}/agent' && .venv/bin/lexguard serve --host 0.0.0.0 --port ${API_PORT}"

start_service scheduler \
  bash -lc "cd '${REPO_ROOT}/agent' && .venv/bin/lexguard scheduler --watch"

start_service web \
  bash -lc "cd '${REPO_ROOT}/web' && NEXT_PUBLIC_API_BASE_URL=http://localhost:${API_PORT} pnpm dev --port ${WEB_PORT}"

echo ""
echo "Lexguard is starting:"
echo "  MCP server   http://127.0.0.1:${MCP_PORT}/mcp"
echo "  API          http://localhost:${API_PORT}"
echo "  Web UI       http://localhost:${WEB_PORT}"
echo ""
echo "Logs: ${LOG_DIR}/"
echo "Press Ctrl+C to stop all services (or run 'make stop' from another terminal)."
echo ""

# Keep the script alive until interrupted; child logs stay in .dev-logs/.
wait
