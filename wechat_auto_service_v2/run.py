#!/usr/bin/env python3
import argparse
import json
import logging
import threading
import time
from pathlib import Path

import uvicorn

from .api_app import create_api_app
from .runtime import WeChatAutoRuntime
from .ws_app import create_ws_app


class UvicornThread(threading.Thread):
    def __init__(self, app, host: str, port: int, name: str):
        super().__init__(daemon=True, name=name)
        self.server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False)
        )

    def run(self) -> None:
        self.server.run()

    def stop(self) -> None:
        self.server.should_exit = True


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config not found: {path}")
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="WeChat Auto Service v2 (wechat08-compatible)")
    parser.add_argument("--config", default="wechat_auto_service_v2/config.json")
    parser.add_argument("--no-automation", action="store_true", help="Start servers without Selenium automation")
    args = parser.parse_args()

    cfg = load_config(args.config)
    log_level = (cfg.get("logging") or {}).get("level") or "INFO"
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    runtime = WeChatAutoRuntime(cfg)

    api_cfg = cfg.get("server") or {}
    api_host = api_cfg.get("api_host", "127.0.0.1")
    api_port = int(api_cfg.get("api_port", 8059))
    ws_host = api_cfg.get("ws_host", "127.0.0.1")
    ws_port = int(api_cfg.get("ws_port", 8088))

    api_app = create_api_app(runtime)
    ws_app = create_ws_app(runtime)

    api_server = UvicornThread(api_app, api_host, api_port, name="wechat08-api")
    ws_server = UvicornThread(ws_app, ws_host, ws_port, name="wechat08-ws")

    api_server.start()
    ws_server.start()

    if not args.no_automation:
        ok = runtime.start_automation()
        if not ok:
            runtime.logger.error("Automation failed to start. Servers are still running.")

    runtime.logger.info("wechat08_api_base: http://%s:%s/api", api_host, api_port)
    runtime.logger.info("wechat08_ws_base: ws://%s:%s/ws", ws_host, ws_port)
    runtime.logger.info("wxid: %s", runtime.bot_wxid)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        runtime.stop_automation()
        api_server.stop()
        ws_server.stop()
        time.sleep(0.5)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
