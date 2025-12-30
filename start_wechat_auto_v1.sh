#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

CFG_EXAMPLE="config.example.json"
CFG="config.json"
REQ="requirements.txt"

log() { printf '[wechat-auto-reply][v1] %s\n' "$*"; }
err() { printf '[wechat-auto-reply][v1][error] %s\n' "$*" >&2; }

usage() {
  cat <<'EOF'
One-click launcher for wechat-auto-reply V1 (Legacy: Selenium + direct LLM).

Usage:
  ./start_wechat_auto_v1.sh [command]

Commands:
  start      Start V1 (default; opens Chrome QR for login)
  restart    Restart V1 and browser profile
  stop       Stop running V1
  install    Create/activate venv and pip install dependencies
  setup      Create config.json from config.example.json (if missing)
  open       Open https://wx.qq.com/ in Chrome using the configured profile
  help       Show help
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
  log "note: set AI_API_KEY in environment for safer key handling"
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

profile_dir() {
  python - "$CFG" <<'PY'
import json, os, sys
cfg_path = sys.argv[1]
cfg = json.load(open(cfg_path, "r", encoding="utf-8"))
ud = ((cfg.get("web_monitor") or {}).get("user_data_dir") or "wechat_user_data_bot")
print(os.path.abspath(ud))
PY
}

stop_service() {
  local pids=""
  pids="$(pgrep -f "python .*main\\.py" || true)"
  if [ -n "$pids" ]; then
    log "stopping V1: $pids"
    kill -INT $pids >/dev/null 2>&1 || true
    sleep 0.8
    pids="$(pgrep -f "python .*main\\.py" || true)"
    if [ -n "$pids" ]; then
      kill $pids >/dev/null 2>&1 || true
      sleep 0.5
    fi
  fi
}

open_wechat() {
  setup_cfg
  local prof
  prof="$(profile_dir)"
  log "opening wx.qq.com with Chrome profile: $prof"
  # macOS "open" will use Chrome if -a is available
  if command -v open >/dev/null 2>&1; then
    open -a "Google Chrome" --args "--user-data-dir=$prof" "https://wx.qq.com/" || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "https://wx.qq.com/" || true
  else
    err "no opener found (open/xdg-open)"
    return 1
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
  start_service
}

start_service() {
  setup_cfg
  log "starting V1 (扫码登录会自动弹出浏览器)..."
  python main.py
}

main_cli() {
  ensure_python

  cmd="${1:-start}"
  if [ "$cmd" = "start" ] || [ "$cmd" = "restart" ] || [ "$cmd" = "stop" ] || [ "$cmd" = "install" ] || [ "$cmd" = "setup" ] || [ "$cmd" = "open" ] || [ "$cmd" = "help" ]; then
    shift || true
  else
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
      start_service
      ;;
    restart)
      activate_venv
      restart_service
      ;;
    stop)
      stop_service
      ;;
    open)
      open_wechat
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main_cli "$@"

