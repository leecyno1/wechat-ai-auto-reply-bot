from typing import Any, Optional

from fastapi import Body, FastAPI, Query
from pydantic import BaseModel, Field

from .runtime import WeChatAutoRuntime


class SendTxtRequest(BaseModel):
    Wxid: str = Field(..., description="Bot wxid")
    ToWxid: str = Field(..., description="Target wxid (friend/group)")
    Content: str = Field(..., description="Text content")
    Type: int = Field(1, description="Message type, 1=text")
    At: str = Field("", description="Comma separated at targets (optional)")


class UploadImgRequest(BaseModel):
    Wxid: str
    ToWxid: str
    Base64: str


class SendVoiceRequest(BaseModel):
    Wxid: str
    ToWxid: str
    Base64: str
    VoiceTime: int = 0
    Type: int = 4


class SendAppRequest(BaseModel):
    Wxid: str
    ToWxid: str
    Xml: str
    Type: int = 0


def create_api_app(runtime: WeChatAutoRuntime) -> FastAPI:
    app = FastAPI(title="WeChat Auto Service v2 (API)", version="2.0")

    @app.get("/health")
    def health() -> dict:
        return runtime.ok(
            {
                "service": "wechat_auto_service_v2",
                "uptime_sec": int(__import__("time").time() - runtime.stats["started_at"]),
            }
        )

    @app.get("/api/Msg/WebSocketStatus")
    def ws_status() -> dict:
        return runtime.ok(
            {
                "wxids": list(runtime.ws_clients.keys()),
                "connections": runtime.stats.get("ws_connections", 0),
            }
        )

    @app.get("/api/Msg/TestWebSocket")
    def test_ws(wxid: Optional[str] = Query(default=None)) -> dict:
        runtime.enqueue_test_payload(wxid=wxid or runtime.bot_wxid)
        return runtime.ok({"pushed": True, "wxid": wxid or runtime.bot_wxid})

    @app.get("/api/Msg/SyncAndPush")
    def sync_and_push(wxid: str = Query(...)) -> dict:
        # Selenium mode already pushes in real-time; this is a best-effort compatibility endpoint.
        runtime.enqueue_test_payload(wxid=wxid)
        return runtime.ok({"scheduled": True, "wxid": wxid})

    @app.post("/api/Msg/Sync")
    def sync(body: dict = Body(default_factory=dict)) -> dict:
        # Minimal wechat-go compatible shape. Return no AddMsgs; realtime WS is the primary channel.
        synckey = body.get("Synckey") or ""
        return runtime.ok({"Synckey": synckey, "AddMsgs": []})

    @app.post("/api/Login/HeartBeatLong")
    def login_heartbeat_long(wxid: Optional[str] = Query(default=None)) -> dict:
        return runtime.ok({"wxid": wxid or runtime.bot_wxid})

    @app.post("/api/User/GetContractProfile")
    def get_profile(wxid: Optional[str] = Query(default=None), body: Optional[dict] = Body(default=None)) -> dict:
        req_wxid = wxid or (body or {}).get("Wxid") or runtime.bot_wxid
        if req_wxid != runtime.bot_wxid:
            return runtime.err(404, f"unknown wxid: {req_wxid}")
        return runtime.ok({"wxid": runtime.bot_wxid, "nickname": runtime.bot_nickname})

    @app.post("/api/Msg/SendTxt")
    def send_txt(req: SendTxtRequest) -> dict:
        try:
            runtime.logger.info("wechat08 SendTxt: to=%s len=%s", req.ToWxid, len(req.Content or ""))
            accepted, job_id = runtime.enqueue_text(req.ToWxid, req.Content)
            if not accepted:
                return runtime.err(503, "automation not ready (selenium not running)")
            # Return immediately to avoid LangBot HTTP client read timeout.
            return runtime.ok({"accepted": True, "jobId": job_id})
        except Exception as exc:
            return runtime.err(500, str(exc))

    @app.get("/api/Msg/SendTxtStatus")
    def send_txt_status(jobId: int = Query(...)) -> dict:
        job = runtime.get_send_job(jobId)
        if not job:
            return runtime.err(404, f"unknown jobId: {jobId}")
        return runtime.ok(job)

    @app.post("/api/Msg/UploadImg")
    def upload_img(req: UploadImgRequest) -> dict:
        return runtime.err(501, "UploadImg not supported by selenium-web automation in v2")

    @app.post("/api/Msg/SendVoice")
    def send_voice(req: SendVoiceRequest) -> dict:
        return runtime.err(501, "SendVoice not supported by selenium-web automation in v2")

    @app.post("/api/Msg/SendApp")
    def send_app(req: SendAppRequest) -> dict:
        return runtime.err(501, "SendApp not supported by selenium-web automation in v2")

    @app.post("/api/Tools/CdnDownloadImage")
    def cdn_download_image(payload: dict = Body(default_factory=dict)) -> dict:
        return runtime.err(501, "CdnDownloadImage not supported by selenium-web automation in v2")

    @app.post("/api/Tools/DownloadVoice")
    def download_voice(payload: dict = Body(default_factory=dict)) -> dict:
        return runtime.err(501, "DownloadVoice not supported by selenium-web automation in v2")

    return app
