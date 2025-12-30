import asyncio
import time
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .runtime import WeChatAutoRuntime


def _resolve_wxid_from_request(ws: WebSocket, fallback: str) -> str:
    wxid = ws.path_params.get("wxid") if hasattr(ws, "path_params") else None
    if not wxid:
        wxid = ws.query_params.get("wxid")
    return (wxid or fallback).strip()


def create_ws_app(runtime: WeChatAutoRuntime) -> FastAPI:
    async def lifespan(app: FastAPI):
        task = asyncio.create_task(runtime.ws_broadcast_loop(), name="wechat08-ws-broadcast-loop")
        yield
        task.cancel()
        with contextlib.suppress(Exception):
            await task

    import contextlib

    app = FastAPI(title="WeChat Auto Service v2 (WS)", version="2.0", lifespan=lifespan)

    @app.get("/ws/health")
    def health() -> dict:
        return runtime.ok({"service": "wechat_auto_service_v2", "ts": int(time.time())})

    @app.get("/ws/stats")
    def stats() -> dict:
        return runtime.ok(runtime.stats)

    @app.post("/msg/SyncMessage/{wxid}")
    def sync_message(wxid: str) -> dict:
        # wechat8061-compatible trigger endpoint; selenium mode already pushes in real-time.
        runtime.enqueue_test_payload(wxid=wxid)
        return runtime.ok({"scheduled": True, "wxid": wxid})

    async def _ws_handler(ws: WebSocket):
        wxid = _resolve_wxid_from_request(ws, runtime.bot_wxid)
        await ws.accept()
        await ws.send_text(f"{wxid}已连接")
        await runtime.ws_register(wxid, ws)
        try:
            while True:
                # Keep the socket open; we don't require client messages.
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            await runtime.ws_unregister(wxid, ws)

    @app.websocket("/ws")
    async def ws_root(ws: WebSocket):
        await _ws_handler(ws)

    @app.websocket("/ws/ws")
    async def ws_ws(ws: WebSocket):
        await _ws_handler(ws)

    @app.websocket("/ws/{wxid}")
    async def ws_path(ws: WebSocket, wxid: str):
        await _ws_handler(ws)

    @app.websocket("/ws/ws/{wxid}")
    async def ws_ws_path(ws: WebSocket, wxid: str):
        await _ws_handler(ws)

    return app
