#!/usr/bin/env bash
# Start SvgBot backend (FastAPI) and frontend (Vite) from the project root.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
VENV_PY=""

cleanup() {
  local pids
  pids=$(jobs -p 2>/dev/null || true)
  if [ -n "${pids}" ]; then
    echo ""
    echo "Shutting down..."
    kill ${pids} 2>/dev/null || true
    wait ${pids} 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

is_windows_shell() {
  case "$(uname -s 2>/dev/null || true)" in
    MINGW* | MSYS* | CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    echo python3
  elif command -v python >/dev/null 2>&1; then
    echo python
  else
    echo "Python not found. Install Python 3.11+ and try again." >&2
    exit 1
  fi
}

venv_python() {
  if [ -n "${VENV_PY}" ]; then
    echo "${VENV_PY}"
    return
  fi
  if [ -x "${ROOT}/backend/.venv/bin/python" ]; then
    VENV_PY="${ROOT}/backend/.venv/bin/python"
  elif [ -x "${ROOT}/backend/.venv/Scripts/python.exe" ]; then
    VENV_PY="${ROOT}/backend/.venv/Scripts/python.exe"
  else
    echo "Backend venv python not found." >&2
    exit 1
  fi
  echo "${VENV_PY}"
}

ensure_backend_venv() {
  local py venv_py
  py="$(python_cmd)"

  if [ ! -d "${ROOT}/backend/.venv" ]; then
    echo "Creating backend virtual environment..."
    (cd "${ROOT}/backend" && "${py}" -m venv .venv)
  fi

  venv_py="$(venv_python)"

  if [ -f "${ROOT}/backend/requirements.txt" ]; then
    echo "Installing backend dependencies from requirements.txt..."
    "${venv_py}" -m pip install -q -r "${ROOT}/backend/requirements.txt"
  fi

  install_starvector "${venv_py}"
}

install_starvector() {
  local venv_py=$1
  if "${venv_py}" -c "import starvector" >/dev/null 2>&1; then
    return
  fi
  if [ ! -f "${ROOT}/backend/requirements-starvector.txt" ]; then
    return
  fi

  echo "Installing StarVector package (requirements-starvector.txt)..."
  if "${venv_py}" -m pip install -q -r "${ROOT}/backend/requirements-starvector.txt"; then
    return
  fi

  echo "Full StarVector install failed (often flash_attn on Windows). Retrying without deps..."
  "${venv_py}" -m pip install -q --no-deps "git+https://github.com/joanrod/star-vector.git"
  "${venv_py}" -m pip install -q -r "${ROOT}/backend/requirements-starvector-deps.txt"
}

kill_port() {
  local port=$1
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids=$(lsof -ti ":${port}" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "${pids}" ]; then
      echo "Stopping prior listener on port ${port}..."
      kill ${pids} 2>/dev/null || true
    fi
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" 2>/dev/null || true
  elif is_windows_shell; then
    local line pid
    while IFS= read -r line; do
      pid=$(echo "${line}" | awk '{print $NF}')
      if [ -n "${pid}" ] && [ "${pid}" != "0" ]; then
        echo "Stopping prior listener on port ${port} (PID ${pid})..."
        taskkill //F //PID "${pid}" 2>/dev/null || true
      fi
    done < <(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTENING || true)
  fi
}

kill_stale_venv_procs() {
  local venv="${ROOT}/backend/.venv"
  if command -v pgrep >/dev/null 2>&1; then
    local pids
    pids=$(pgrep -f "${venv}" 2>/dev/null || true)
    if [ -n "${pids}" ]; then
      echo "Stopping stale venv processes..."
      kill ${pids} 2>/dev/null || true
    fi
  elif is_windows_shell && command -v powershell.exe >/dev/null 2>&1; then
    local venv_win
    venv_win=$(echo "${venv}" | sed 's|/|\\|g')
    powershell.exe -NoProfile -Command "
      Get-Process python,pythonw,uvicorn -ErrorAction SilentlyContinue |
        Where-Object { \$_.Path -and \$_.Path -like '*${venv_win}*' } |
        ForEach-Object {
          Write-Host \"Stopping stale venv process: \$(\$_.ProcessName) (PID \$(\$_.Id))\"
          Stop-Process -Id \$_.Id -Force -ErrorAction SilentlyContinue
        }
    " 2>/dev/null || true
  fi
}

stop_stale_backend() {
  kill_port "${BACKEND_PORT}"
  kill_stale_venv_procs
  sleep 1
}

wait_for_backend() {
  local venv_py url i
  venv_py="$(venv_python)"
  url="http://127.0.0.1:${BACKEND_PORT}/health"
  echo "Waiting for backend at ${url}..."
  for i in $(seq 1 60); do
    if "${venv_py}" -c "
import sys
import urllib.request
try:
    urllib.request.urlopen('${url}', timeout=2)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
      echo "Backend is ready."
      return 0
    fi
    sleep 0.5
  done
  echo "Backend did not become ready on port ${BACKEND_PORT} within 30s." >&2
  echo "Check backend output above for import or startup errors." >&2
  return 1
}

if [ ! -d "${ROOT}/frontend/node_modules" ]; then
  echo "Installing frontend dependencies..."
  (cd "${ROOT}/frontend" && npm install)
fi

ensure_backend_venv
export PYTHONPATH="${ROOT}/backend"
unset STARVECTOR_ENABLED 2>/dev/null || true

stop_stale_backend

echo "Starting backend on http://127.0.0.1:${BACKEND_PORT}"
# Important: limit `--reload` scope to ./app so watchfiles ignores .venv and the
# StarVector/HF model cache. A model download or .pyc regeneration otherwise
# triggers a worker reload mid-import and causes WinError 6714 on Windows
# (and slow churn on Linux/macOS).
# Do not pass --reload-exclude '.venv/*' here: Git Bash expands that glob into
# separate paths before invoking Windows python.exe, and uvicorn rejects them.
# --reload-dir app already excludes .venv from the watch set.
(
  cd "${ROOT}/backend"
  set -f
  exec "$(venv_python)" -m uvicorn app.main:app \
    --reload \
    --reload-dir app \
    --reload-exclude '*.pyc' \
    --host 0.0.0.0 --port "${BACKEND_PORT}"
) &

wait_for_backend

echo "Starting frontend on http://127.0.0.1:${FRONTEND_PORT}"
(
  cd "${ROOT}/frontend"
  exec npm run dev -- --host --port "${FRONTEND_PORT}"
) &

echo ""
echo "SvgBot is running."
echo "  Frontend: http://127.0.0.1:${FRONTEND_PORT}"
echo "  Backend:  http://127.0.0.1:${BACKEND_PORT}"
echo "  API docs: http://127.0.0.1:${BACKEND_PORT}/docs"
echo ""
echo "Press Ctrl+C to stop both."

wait
