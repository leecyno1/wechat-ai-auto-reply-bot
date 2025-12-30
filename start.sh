#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

usage() {
  cat <<'EOF'
wechat-auto-reply launcher

Usage:
  ./start.sh [command]

Commands:
  v1         Start V1 (legacy, direct LLM)
  v2         Start V2 (wechat08 gateway for LangBot)
  restart-v1 Restart V1 (clean profile and relaunch)
  restart-v2 Restart V2 (clean profile and relaunch)
  app        Start a local "button UI" launcher (http://127.0.0.1:8099)
  help       Show help

Examples:
  ./start.sh v2
  ./start.sh app
EOF
}

cmd="${1:-help}"
case "$cmd" in
  v1)
    exec ./start_wechat_auto_v1.sh start
    ;;
  v2)
    exec ./start_wechat_auto_v2.sh start
    ;;
  restart-v1)
    exec ./start_wechat_auto_v1.sh restart
    ;;
  restart-v2)
    exec ./start_wechat_auto_v2.sh restart
    ;;
  app)
    exec python3 launcher_app.py --open
    ;;
  help|*)
    usage
    ;;
esac

