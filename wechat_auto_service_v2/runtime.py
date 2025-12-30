import asyncio
import json
import logging
import queue
import random
import threading
import time
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Optional

from modules.web_monitor import WebMonitor


def _wechat08_ok(data: Any = None, message: str = "ok") -> dict:
    return {"Code": 0, "Success": True, "Message": message, "Data": data if data is not None else {}}


def _wechat08_err(code: int, message: str) -> dict:
    return {"Code": int(code), "Success": False, "Message": message, "Data": {}}


def _strip_chatroom_suffix(wxid_or_name: str) -> str:
    if isinstance(wxid_or_name, str) and wxid_or_name.endswith("@chatroom"):
        return wxid_or_name[: -len("@chatroom")]
    return wxid_or_name


@dataclass(frozen=True)
class PublishItem:
    account_wxid: str
    payload: dict


@dataclass
class SendJob:
    job_id: int
    to_wxid: str
    content: str
    created_at: float
    max_attempts: int
    require_ack: bool
    ack_timeout_sec: float
    done: threading.Event = field(default_factory=threading.Event)
    ok: bool = False
    error: str = ""


class WeChatAutoRuntime:
    """
    Runtime that:
    - runs Selenium-based WeChat Web automation (login + message monitoring)
    - exposes a wechat08-compatible message stream (WS) + send APIs (HTTP)
    """

    def __init__(self, config: dict):
        self.config = config
        self.bot_wxid: str = (config.get("bot") or {}).get("wxid") or "wxid_unknown"
        self.bot_nickname: str = (config.get("bot") or {}).get("nickname") or self.bot_wxid

        self.logger = logging.getLogger("wechat_auto_service_v2")

        self._msg_id = count(1)
        self._outbox: queue.Queue[PublishItem] = queue.Queue()

        self._web_monitor: Optional[WebMonitor] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._automation_lock = threading.Lock()
        self._automation_running = False

        send_cfg = dict(config.get("send") or {})
        self._send_require_ack: bool = bool(send_cfg.get("require_ack", True))
        self._send_ack_timeout_sec: float = float(send_cfg.get("ack_timeout_sec", 3.0))
        self._send_max_attempts: int = int(send_cfg.get("max_attempts", 3))
        self._send_backoff_base_sec: float = float(send_cfg.get("backoff_base_sec", 0.6))
        self._send_backoff_max_sec: float = float(send_cfg.get("backoff_max_sec", 4.0))
        self._send_request_timeout_sec: float = float(send_cfg.get("request_timeout_sec", 12.0))

        self._send_job_id = count(1)
        self._send_queue: queue.Queue[Optional[SendJob]] = queue.Queue()
        self._send_thread: Optional[threading.Thread] = None
        self._send_pending_lock = threading.Lock()
        self._send_pending: dict[tuple[str, str], SendJob] = {}
        self._send_by_id_lock = threading.Lock()
        self._send_by_id: dict[int, SendJob] = {}

        merge_cfg = dict(config.get("merge") or {})
        self._merge_enabled: bool = bool(merge_cfg.get("enabled", True))
        self._merge_window_sec: float = float(merge_cfg.get("window_sec", 0.8))
        self._merge_max_messages: int = int(merge_cfg.get("max_messages", 5))
        self._merge_max_chars: int = int(merge_cfg.get("max_chars", 2000))
        self._merge_lock = threading.Lock()
        self._merge_buffers: dict[tuple[str, bool], dict[str, Any]] = {}

        self.ws_clients: dict[str, set[Any]] = {}
        self._ws_clients_lock = threading.Lock()

        self.stats = {
            "received": 0,
            "sent": 0,
            "ws_connections": 0,
            "started_at": time.time(),
        }

    # -----------------------
    # Automation (Selenium)
    # -----------------------
    def start_automation(self) -> bool:
        with self._automation_lock:
            if self._automation_running:
                return True

            monitor_cfg = dict(self.config.get("web_monitor") or {})
            monitor_cfg.setdefault("trigger_keywords", [])
            monitor_cfg.setdefault("auto_reply_all", False)

            def _on_message(message_data: dict) -> Optional[str]:
                self._handle_incoming_from_web_monitor(message_data)
                return None

            self._web_monitor = WebMonitor(
                logger=self.logger,
                ai_model=None,
                config=monitor_cfg,
                message_callback=_on_message,
            )

            if not self._web_monitor.initialize():
                self.logger.error("WeChat Web initialization/login failed.")
                self._web_monitor = None
                return False

            self._automation_running = True
            self._monitor_thread = threading.Thread(target=self._web_monitor.monitor_messages, daemon=True)
            self._monitor_thread.start()
            self._start_send_worker()
            self.logger.info("WeChat automation started.")
            return True

    def stop_automation(self) -> None:
        with self._automation_lock:
            self._automation_running = False
            if self._web_monitor:
                try:
                    self._web_monitor.close()
                except Exception:
                    pass
            self._web_monitor = None

        # Stop send worker
        try:
            self._send_queue.put_nowait(None)
        except Exception:
            pass
        if self._send_thread and self._send_thread.is_alive():
            self._send_thread.join(timeout=2)
        self._send_thread = None
        with self._send_pending_lock:
            for job in self._send_pending.values():
                job.ok = False
                job.error = "automation stopped"
                job.done.set()
            self._send_pending.clear()

        with self._merge_lock:
            for buf in self._merge_buffers.values():
                timer = buf.get("timer")
                if timer:
                    try:
                        timer.cancel()
                    except Exception:
                        pass
            self._merge_buffers.clear()

    def _handle_incoming_from_web_monitor(self, message_data: dict) -> None:
        try:
            contact = message_data.get("from") or message_data.get("sender") or "Unknown"
            content = message_data.get("content") or ""
            ts = message_data.get("timestamp") or time.time()

            is_group = bool(message_data.get("is_group", False))
            if not is_group:
                try:
                    if self._web_monitor is not None:
                        is_group = bool(getattr(self._web_monitor, "_is_group_chat")())
                except Exception:
                    is_group = False

            if not self._merge_enabled:
                self._emit_incoming_message(contact=str(contact), content=str(content), ts=float(ts), is_group=is_group)
                return

            key = (str(contact), bool(is_group))
            content_str = str(content)
            ts_f = float(ts)

            def _schedule_flush() -> None:
                timer = threading.Timer(self._merge_window_sec, self._flush_merge, args=(key,))
                timer.daemon = True
                self._merge_buffers[key]["timer"] = timer
                timer.start()

            flush_now = False
            with self._merge_lock:
                buf = self._merge_buffers.get(key)
                if not buf:
                    buf = {"parts": [], "last_ts": ts_f, "timer": None}
                    self._merge_buffers[key] = buf
                buf["parts"].append(content_str)
                buf["last_ts"] = ts_f

                timer = buf.get("timer")
                if timer:
                    try:
                        timer.cancel()
                    except Exception:
                        pass

                if len(buf["parts"]) >= self._merge_max_messages:
                    flush_now = True
                elif sum(len(p) for p in buf["parts"]) >= self._merge_max_chars:
                    flush_now = True

                if not flush_now:
                    _schedule_flush()

            if flush_now:
                self._flush_merge(key)
        except Exception as exc:
            self.logger.exception("Failed to handle incoming message: %s", exc)

    def _flush_merge(self, key: tuple[str, bool]) -> None:
        contact, is_group = key
        with self._merge_lock:
            buf = self._merge_buffers.pop(key, None)
        if not buf:
            return
        parts = [p for p in (buf.get("parts") or []) if isinstance(p, str) and p.strip()]
        if not parts:
            return
        combined = "\n".join(parts) if len(parts) > 1 else parts[0]
        ts = float(buf.get("last_ts") or time.time())
        self._emit_incoming_message(contact=contact, content=combined, ts=ts, is_group=is_group)

    def _emit_incoming_message(self, contact: str, content: str, ts: float, is_group: bool) -> None:
        from_user = f"{contact}@chatroom" if is_group else str(contact)
        # wechat08 group messages often prefix sender-id line: "<sender>:\n<content>"
        # use a placeholder sender to keep LangBot's wechat08 parser happy.
        normalized_content = f"member:\n{content}" if is_group else str(content)

        msg_id = next(self._msg_id)
        msg = {
            "fromUser": from_user,
            "toUser": self.bot_wxid,
            "content": normalized_content,
            "msgType": 1,
            "msgId": msg_id,
            "newMsgId": msg_id,
            "createTime": int(ts),
            "pushContent": "",
            "msgSource": "",
        }
        payload = {
            "type": "wechat_message",
            "wxid": self.bot_wxid,
            "timestamp": int(time.time()),
            "count": 1,
            "messages": [msg],
        }
        self._outbox.put(PublishItem(account_wxid=self.bot_wxid, payload=payload))
        self.stats["received"] += 1

    def _start_send_worker(self) -> None:
        if self._send_thread and self._send_thread.is_alive():
            return

        def _loop() -> None:
            while True:
                job = self._send_queue.get()
                if job is None:
                    return
                key = (job.to_wxid, job.content)
                try:
                    job.ok = self._perform_send_job(job)
                    if not job.ok and not job.error:
                        job.error = "send failed"
                except Exception as exc:
                    job.ok = False
                    job.error = str(exc)
                finally:
                    job.done.set()
                    with self._send_pending_lock:
                        self._send_pending.pop(key, None)

        self._send_thread = threading.Thread(target=_loop, daemon=True, name="wechat_auto_send_worker")
        self._send_thread.start()

    def enqueue_text(self, to_wxid: str, content: str) -> tuple[bool, int]:
        """
        Enqueue a send job and return (accepted, job_id).
        This is the preferred mode for HTTP callers to avoid blocking on Selenium/UI.
        """
        to_wxid = str(to_wxid)
        content = "" if content is None else str(content)
        if not content.strip():
            return False, 0

        with self._automation_lock:
            if not self._automation_running or not self._web_monitor:
                return False, 0

        self._start_send_worker()
        key = (to_wxid, content)
        with self._send_pending_lock:
            existing = self._send_pending.get(key)
            if existing:
                return True, int(existing.job_id)

            job = SendJob(
                job_id=next(self._send_job_id),
                to_wxid=to_wxid,
                content=content,
                created_at=time.time(),
                max_attempts=self._send_max_attempts,
                require_ack=self._send_require_ack,
                ack_timeout_sec=self._send_ack_timeout_sec,
            )
            self._send_pending[key] = job
            with self._send_by_id_lock:
                self._send_by_id[int(job.job_id)] = job
            self._send_queue.put(job)
            return True, int(job.job_id)

    def get_send_job(self, job_id: int) -> Optional[dict]:
        with self._send_by_id_lock:
            job = self._send_by_id.get(int(job_id))
        if not job:
            return None
        return {
            "jobId": int(job.job_id),
            "toWxid": job.to_wxid,
            "createdAt": float(job.created_at),
            "done": bool(job.done.is_set()),
            "ok": bool(job.ok),
            "error": str(job.error or ""),
        }

    def _perform_send_job(self, job: SendJob) -> bool:
        target = _strip_chatroom_suffix(job.to_wxid)
        max_attempts = max(1, int(job.max_attempts))
        base = max(0.05, float(self._send_backoff_base_sec))
        cap = max(base, float(self._send_backoff_max_sec))

        for attempt in range(1, max_attempts + 1):
            with self._automation_lock:
                monitor = self._web_monitor
                running = self._automation_running
            if not running or not monitor:
                job.error = "WeChat automation not initialized"
                return False

            try:
                if job.require_ack:
                    ok = bool(monitor.send_message_with_ack(target, job.content, ack_timeout_sec=job.ack_timeout_sec))
                else:
                    ok = bool(monitor.send_message(target, job.content))
            except Exception as exc:
                ok = False
                job.error = str(exc)

            if ok:
                self.stats["sent"] += 1
                self._publish_self_send(job.to_wxid, job.content)
                return True

            if attempt < max_attempts:
                delay = min(cap, base * (1.8 ** (attempt - 1)))
                delay += random.uniform(0.0, 0.2)
                self.logger.warning(
                    "send retry scheduled: to=%s attempt=%s/%s delay=%.2fs err=%s",
                    job.to_wxid,
                    attempt,
                    max_attempts,
                    delay,
                    job.error or "ack timeout",
                )
                time.sleep(delay)

        return False

    def send_text(self, to_wxid: str, content: str) -> bool:
        accepted, job_id = self.enqueue_text(to_wxid, content)
        if not accepted or not job_id:
            return False
        job = None
        with self._send_by_id_lock:
            job = self._send_by_id.get(int(job_id))
        if not job:
            return False
        job.done.wait(timeout=float(self._send_request_timeout_sec))
        return bool(job.ok)

    def _publish_self_send(self, to_wxid: str, content: str) -> None:
        try:
            msg_id = next(self._msg_id)
            msg = {
                "fromUser": self.bot_wxid,
                "toUser": to_wxid,
                "content": content,
                "msgType": 1,
                "msgId": msg_id,
                "newMsgId": msg_id,
                "createTime": int(time.time()),
                "pushContent": "",
                "msgSource": "",
            }
            payload = {
                "type": "wechat_message",
                "wxid": self.bot_wxid,
                "timestamp": int(time.time()),
                "count": 1,
                "messages": [msg],
            }
            self._outbox.put(PublishItem(account_wxid=self.bot_wxid, payload=payload))
        except Exception:
            # best-effort only
            return

    def enqueue_test_payload(self, wxid: Optional[str] = None) -> None:
        wxid = wxid or self.bot_wxid
        payload = {
            "type": "test_periodic",
            "wxid": wxid,
            "timestamp": int(time.time()),
            "count": 0,
            "messages": [],
        }
        self._outbox.put(PublishItem(account_wxid=wxid, payload=payload))

    # -----------------------
    # WebSocket hub
    # -----------------------
    async def ws_register(self, account_wxid: str, ws: Any) -> None:
        with self._ws_clients_lock:
            self.ws_clients.setdefault(account_wxid, set()).add(ws)
            self.stats["ws_connections"] = sum(len(v) for v in self.ws_clients.values())

    async def ws_unregister(self, account_wxid: str, ws: Any) -> None:
        with self._ws_clients_lock:
            if account_wxid in self.ws_clients and ws in self.ws_clients[account_wxid]:
                self.ws_clients[account_wxid].remove(ws)
                if not self.ws_clients[account_wxid]:
                    del self.ws_clients[account_wxid]
            self.stats["ws_connections"] = sum(len(v) for v in self.ws_clients.values())

    async def ws_broadcast_loop(self) -> None:
        while True:
            item: PublishItem = await asyncio.to_thread(self._outbox.get)
            text = json.dumps(item.payload, ensure_ascii=False)
            with self._ws_clients_lock:
                clients = list(self.ws_clients.get(item.account_wxid, set()))
            if not clients:
                continue
            stale: list[Any] = []
            for ws in clients:
                try:
                    await ws.send_text(text)
                except Exception:
                    stale.append(ws)
            if stale:
                with self._ws_clients_lock:
                    for ws in stale:
                        if item.account_wxid in self.ws_clients and ws in self.ws_clients[item.account_wxid]:
                            self.ws_clients[item.account_wxid].remove(ws)
                    if item.account_wxid in self.ws_clients and not self.ws_clients[item.account_wxid]:
                        del self.ws_clients[item.account_wxid]
                    self.stats["ws_connections"] = sum(len(v) for v in self.ws_clients.values())

    # -----------------------
    # Response helpers
    # -----------------------
    def ok(self, data: Any = None, message: str = "ok") -> dict:
        return _wechat08_ok(data=data, message=message)

    def err(self, code: int, message: str) -> dict:
        return _wechat08_err(code=code, message=message)
