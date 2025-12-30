#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

V2_DIR="wechat_auto_service_v2"
CFG_EXAMPLE="${V2_DIR}/config.example.json"
CFG="${V2_DIR}/config.json"
REQ="${V2_DIR}/requirements.txt"

log() { printf '[wechat-auto-reply] %s\n' "$*"; }
err() { printf '[wechat-auto-reply][error] %s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
One-click launcher for wechat-auto-reply (v2 wechat08-compatible gateway).

Usage:
  ./start_wechat_auto_v2.sh [command] [options]

Commands:
  start      Start service (default; opens Chrome QR for login)
  restart    Restart service and browser profile
  install    Create/activate venv and pip install dependencies
  setup      Create config.json from example (if missing)
  help       Show help

Options (for start):
  --no-automation   Start HTTP/WS servers only (no Selenium login)

Examples:
  ./start_wechat_auto_v2.sh
  ./start_wechat_auto_v2.sh install
  ./start_wechat_auto_v2.sh start --no-automation
EOF
}

ensure_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    err "python3 not found"
    exit 1
  fi
}

activate_venv() {
  if [ -d "venv" ]; then
    # shellcheck disable=SC1091
    source "venv/bin/activate"
    return
  fi
  if [ -d ".venv" ]; then
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
    return
  fi
  log "creating venv/ ..."
  python3 -m venv venv
  # shellcheck disable=SC1091
  source "venv/bin/activate"
}

setup_cfg() {
  if [ -f "$CFG" ]; then
    log "config exists: $CFG"
    return
  fi
  if [ ! -f "$CFG_EXAMPLE" ]; then
    err "missing example config: $CFG_EXAMPLE"
    exit 1
  fi
  cp "$CFG_EXAMPLE" "$CFG"
  log "created: $CFG"
}

install_deps() {
  if [ ! -f "$REQ" ]; then
    err "missing requirements: $REQ"
    exit 1
  fi
  log "installing deps from $REQ ..."
  python -m pip install -U pip >/dev/null
  python -m pip install -r "$REQ"
}

start_service() {
  setup_cfg
  log "starting wechat_auto_service_v2 (扫码登录会自动弹出浏览器)..."
  python -m wechat_auto_service_v2.run --config "$CFG" "$@"
}

profile_dir() {
  python - "$CFG" <<'PY'
import json, os, sys
cfg_path = sys.argv[1]
cfg = json.load(open(cfg_path, "r", encoding="utf-8"))
ud = ((cfg.get("web_monitor") or {}).get("user_data_dir") or "wechat_user_data_wechat08_v2")
print(os.path.abspath(ud))
PY
}

stop_service() {
  # Best-effort stop: first SIGINT (graceful), then SIGKILL.
  local pids=""
  pids="$(pgrep -f "wechat_auto_service_v2\\.run --config ${CFG}" || true)"
  if [ -n "$pids" ]; then
    log "stopping service: $pids"
    kill -INT $pids >/dev/null 2>&1 || true
    sleep 0.8
    pids="$(pgrep -f "wechat_auto_service_v2\\.run --config ${CFG}" || true)"
    if [ -n "$pids" ]; then
      kill $pids >/dev/null 2>&1 || true
      sleep 0.5
    fi
  fi
}

restart_service() {
  setup_cfg
  local prof
  prof="$(profile_dir)"
  stop_service
  if [ -n "$prof" ]; then
    log "closing orphaned chrome using profile: $prof"
    pkill -f "$prof" >/dev/null 2>&1 || true
    sleep 0.8
  fi
  start_service "$@"
}

main() {
  ensure_python

  cmd="${1:-start}"
  if [ "$cmd" = "start" ] || [ "$cmd" = "restart" ] || [ "$cmd" = "install" ] || [ "$cmd" = "setup" ] || [ "$cmd" = "help" ]; then
    shift || true
  else
    # allow running start with only options
    cmd="start"
  fi

  case "$cmd" in
    help)
      usage
      ;;
    setup)
      setup_cfg
      ;;
    install)
      activate_venv
      install_deps
      ;;
    start)
      activate_venv
      if ! python -c "import fastapi, uvicorn" >/dev/null 2>&1; then
        log "deps not installed in current venv; run: ./start_wechat_auto_v2.sh install"
      fi
      start_service "$@"
      ;;
    restart)
      activate_venv
      restart_service "$@"
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"
