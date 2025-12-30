#!/usr/bin/env python3
"""
Local "button-style" launcher UI for wechat-auto-reply.

- Starts/stops V1/V2 by invoking the corresponding shell scripts.
- Intended for local use only (binds to 127.0.0.1 by default).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


STATE_DIR = Path(".launcher")
STATE_FILE = STATE_DIR / "state.json"


def _load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _start_process(key: str, command: list[str]) -> tuple[bool, str]:
    state = _load_state()
    existing = state.get(key) or {}
    pid = int(existing.get("pid") or 0)
    if pid and _is_alive(pid):
        return True, f"{key} already running (pid={pid})"

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log_path = str(STATE_DIR / f"{key}.log")

    with open(log_path, "ab") as f:
        proc = subprocess.Popen(
            command,
            stdout=f,
            stderr=subprocess.STDOUT,
            cwd=os.getcwd(),
            start_new_session=True,
        )

    state[key] = {"pid": proc.pid, "started_at": time.time(), "log": log_path, "cmd": command}
    _save_state(state)
    return True, f"started {key} (pid={proc.pid})"


def _stop_process(key: str) -> tuple[bool, str]:
    state = _load_state()
    info = state.get(key) or {}
    pid = int(info.get("pid") or 0)
    if not pid:
        return True, f"{key} not running"

    if not _is_alive(pid):
        state.pop(key, None)
        _save_state(state)
        return True, f"{key} already stopped"

    try:
        os.killpg(pid, signal.SIGINT)
    except Exception:
        try:
            os.kill(pid, signal.SIGINT)
        except Exception:
            pass

    time.sleep(0.8)
    if _is_alive(pid):
        try:
            os.killpg(pid, signal.SIGTERM)
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass

    state.pop(key, None)
    _save_state(state)
    return True, f"stopped {key}"


def _open_url(url: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", url])
        return
    if os.name == "nt":
        os.startfile(url)  # type: ignore[attr-defined]
        return
    subprocess.Popen(["xdg-open", url])


def _html_page(state: dict) -> str:
    def row(key: str, label: str) -> str:
        info = state.get(key) or {}
        pid = int(info.get("pid") or 0)
        alive = pid and _is_alive(pid)
        badge = "RUNNING" if alive else "STOPPED"
        color = "#16a34a" if alive else "#64748b"
        log_path = info.get("log") or ""
        return f"""
        <div class="card">
          <div class="title">
            <div class="name">{label}</div>
            <div class="badge" style="background:{color}">{badge}</div>
          </div>
          <div class="meta">pid: {pid if pid else "-"}</div>
          <div class="meta">log: {log_path if log_path else ".launcher/"+key+".log"}</div>
          <div class="actions">
            <form method="POST" action="/start"><input type="hidden" name="key" value="{key}"/><button class="btn primary" type="submit">Start</button></form>
            <form method="POST" action="/restart"><input type="hidden" name="key" value="{key}"/><button class="btn" type="submit">Restart</button></form>
            <form method="POST" action="/stop"><input type="hidden" name="key" value="{key}"/><button class="btn danger" type="submit">Stop</button></form>
          </div>
        </div>
        """

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>wechat-auto-reply launcher</title>
  <style>
    :root {{
      --bg: #0b1220;
      --panel: #0f172a;
      --muted: #94a3b8;
      --text: #e2e8f0;
      --border: rgba(148,163,184,0.18);
      --btn: rgba(148,163,184,0.10);
      --btn-hover: rgba(148,163,184,0.16);
      --primary: #22c55e;
      --danger: #ef4444;
    }}
    body {{ margin:0; background: radial-gradient(1200px 500px at 20% -10%, rgba(34,197,94,0.18), transparent 70%), var(--bg); color: var(--text); font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial; }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 28px 18px 44px; }}
    .header {{ display:flex; align-items:center; justify-content:space-between; gap: 14px; }}
    h1 {{ font-size: 22px; margin: 0; letter-spacing: 0.2px; }}
    .sub {{ margin-top: 8px; color: var(--muted); font-size: 13px; line-height: 1.5; }}
    .grid {{ display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 18px; }}
    .card {{ background: rgba(15,23,42,0.86); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }}
    .title {{ display:flex; align-items:center; justify-content:space-between; gap: 10px; }}
    .name {{ font-weight: 750; font-size: 15px; }}
    .badge {{ font-size: 12px; padding: 6px 10px; border-radius: 999px; color:#071014; font-weight: 800; letter-spacing: .4px; }}
    .meta {{ color: var(--muted); font-size: 12px; margin-top: 8px; }}
    .actions {{ display:flex; gap: 10px; margin-top: 12px; }}
    .actions form {{ margin:0; }}
    .btn {{ cursor:pointer; border: 1px solid var(--border); background: var(--btn); color: var(--text); padding: 9px 12px; border-radius: 10px; font-weight: 650; }}
    .btn:hover {{ background: var(--btn-hover); }}
    .btn.primary {{ background: rgba(34,197,94,0.14); border-color: rgba(34,197,94,0.30); }}
    .btn.primary:hover {{ background: rgba(34,197,94,0.20); }}
    .btn.danger {{ background: rgba(239,68,68,0.12); border-color: rgba(239,68,68,0.30); }}
    .btn.danger:hover {{ background: rgba(239,68,68,0.18); }}
    .tools {{ display:flex; gap: 10px; margin-top: 14px; flex-wrap: wrap; }}
    .note {{ margin-top: 14px; padding: 12px 14px; border-radius: 12px; border: 1px dashed rgba(148,163,184,0.22); color: var(--muted); font-size: 12px; line-height: 1.6; }}
    code {{ background: rgba(148,163,184,0.10); padding: 2px 6px; border-radius: 8px; color: var(--text); }}
    @media (max-width: 860px) {{ .grid {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="header">
      <div>
        <h1>wechat-auto-reply launcher</h1>
        <div class="sub">一键启动 / 重启 / 停止（本地使用）。启动后会弹出 Chrome 并打开网页微信 <code>wx.qq.com</code>。</div>
      </div>
      <form method="POST" action="/refresh"><button class="btn" type="submit">Refresh</button></form>
    </div>

    <div class="grid">
      {row("v2", "V2 网关（推荐，LangBot wechat08）")}
      {row("v1", "V1 Legacy（直连 LLM，自回复）")}
    </div>

    <div class="tools">
      <form method="POST" action="/open_wechat"><button class="btn primary" type="submit">Open wx.qq.com</button></form>
      <a class="btn" href="/state" style="text-decoration:none; display:inline-flex; align-items:center;">View state.json</a>
    </div>

    <div class="note">
      日志默认写入：<code>.launcher/v1.log</code> / <code>.launcher/v2.log</code><br/>
      若 LangBot 在 Docker 中，配置应使用：<code>host.docker.internal</code>（详见 README_LANGBOT_INTEGRATION.md）。
    </div>
  </div>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _redirect(self, location: str = "/") -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send(200, _html_page(_load_state()))
            return
        if parsed.path == "/state":
            state = _load_state()
            self._send(200, json.dumps(state, ensure_ascii=False, indent=2), "application/json; charset=utf-8")
            return
        self._send(404, "not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="ignore")
        form = parse_qs(raw)
        key = (form.get("key") or [""])[0]

        parsed = urlparse(self.path)
        if parsed.path == "/refresh":
            self._redirect("/")
            return

        if parsed.path == "/open_wechat":
            _open_url("https://wx.qq.com/")
            self._redirect("/")
            return

        if key not in ("v1", "v2"):
            self._send(400, "invalid key", "text/plain; charset=utf-8")
            return

        if parsed.path == "/start":
            cmd = ["bash", "-lc", "./start_wechat_auto_v2.sh start"] if key == "v2" else ["bash", "-lc", "./start_wechat_auto_v1.sh start"]
            ok, msg = _start_process(key, cmd)
            self._redirect("/")
            return

        if parsed.path == "/restart":
            _stop_process(key)
            cmd = ["bash", "-lc", "./start_wechat_auto_v2.sh restart"] if key == "v2" else ["bash", "-lc", "./start_wechat_auto_v1.sh restart"]
            _start_process(key, cmd)
            self._redirect("/")
            return

        if parsed.path == "/stop":
            _stop_process(key)
            self._redirect("/")
            return

        self._send(404, "not found", "text/plain; charset=utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--open", action="store_true", help="Open the launcher page in a browser")
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f"http://{args.host}:{args.port}/"
    print(f"launcher: {url}")
    if args.open:
        _open_url(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

