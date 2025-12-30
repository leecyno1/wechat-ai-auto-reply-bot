# WeChat Auto Service v2（wechat08 兼容版）

目标：把当前仓库的 Selenium 微信网页版能力，收敛成一个“微信自动化服务（登录/监测/发消息）”，并对齐 LangBot 的 `wechat08` 平台适配器（HTTP + WebSocket）。

## 1. 你将得到什么

- 一个独立的 2.0 服务：`wechat_auto_service_v2/`
- HTTP API：对齐 LangBot `wechat08` 所需的 `/api/Msg/*`、`/api/User/*`（最小子集）
- WebSocket：对齐 LangBot `wechat08` 的消息推送协议（`type=wechat_message`，含 `messages=[{fromUser,toUser,content,...}]`）
- Selenium 自动化：复用本仓库的 `modules/web_monitor.py`（扫码登录、监测新消息、发送文本消息）

## 2. 快速启动

1) 准备配置

```bash
cp wechat_auto_service_v2/config.example.json wechat_auto_service_v2/config.json
```

也可以用一键脚本（会自动创建 `config.json` 并启动扫码登录）：

```bash
./start_wechat_auto_v2.sh
```

或用统一入口：

```bash
./start.sh v2
```

2) 安装依赖

```bash
pip install -r wechat_auto_service_v2/requirements.txt
```

3) 启动服务

```bash
python -m wechat_auto_service_v2.run --config wechat_auto_service_v2/config.json
```

首次启动会弹出 Chrome 微信网页版二维码，扫码登录后开始推送消息。

默认端口：
- HTTP：`http://127.0.0.1:8059/api`
- WS：`ws://127.0.0.1:8088/ws`

## 3. LangBot（wechat08）对接方式

在 LangBot 配置里填写（参考 LangBot `docs/WECHAT08_SETUP.md`）：

```yaml
wechat08:
  wechat08_api_base: "http://127.0.0.1:8059/api"
  wechat08_ws_base: "ws://127.0.0.1:8088/ws"
  wxid: "wxid_demo_bot"
```

说明：
- `wxid` 需要与你的 `wechat_auto_service_v2/config.json -> bot.wxid` 一致（本服务是 Selenium 微信网页版，不会自动拿到真实 wxid，所以用“配置约定”的方式对齐适配器）。

## 4. 已实现的 wechat08 兼容接口

- `GET  /api/Msg/WebSocketStatus`
- `GET  /api/Msg/TestWebSocket?wxid=...`
- `GET  /api/Msg/SyncAndPush?wxid=...`（兼容：实际是 push 一个测试 payload）
- `POST /api/Msg/Sync`（兼容：返回空 AddMsgs）
- `POST /api/Msg/SendTxt`（入队即返回，避免 LangBot 默认 10s HTTP 超时）
- `GET  /api/Msg/SendTxtStatus?jobId=...`（调试：查看发送任务状态）
- `POST /api/User/GetContractProfile`
- `POST /api/Login/HeartBeatLong?wxid=...`（兼容：返回 Success）
- `GET  /ws/health`
- `GET  /ws/stats`
- `WS   /ws`、`/ws/ws`、`/ws/{wxid}`、`/ws/ws/{wxid}`
- `POST /msg/SyncMessage/{wxid}`（兼容：push 一个测试 payload）

## 5. 现阶段限制（2.0 的刻意收敛）

- 目前只支持文本发送：`/api/Msg/SendTxt`
- 图片/语音/小程序等接口返回 `501`（后续可以在 Selenium 侧补齐）
- 群消息的发送者信息在 Web 微信里不稳定：服务会用 `member:` 作为占位前缀来满足 LangBot `wechat08` 对群消息的解析逻辑
