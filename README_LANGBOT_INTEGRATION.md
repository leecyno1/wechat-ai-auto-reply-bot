# LangBot 对接手册（wechat08 兼容网关）

本项目推荐的对接方式是：**不在 LangBot 内新增适配器代码**，而是在本仓库启动一个“wechat08 协议兼容网关”（HTTP + WebSocket），让 LangBot 直接使用其内置 `wechat08` 平台适配器。

网关底层依旧是 Selenium 控制 `wx.qq.com`（网页微信）完成登录、收消息与发消息。

## 1. 架构与数据流

- **收消息**：Selenium 从网页端 DOM 监测未读红点/活跃会话，提取消息文本 → 推送到 WebSocket（wechat08 兼容数据结构）→ LangBot 收到后进入消息处理流水线。
- **发消息**：LangBot 调用 HTTP `/api/Msg/SendTxt` → 网关将“发送任务”入队（立即返回，避免 LangBot 10s 超时）→ Selenium 选择会话并发送。

为什么要“立即返回”：
- LangBot 的 `wechat08` HTTP client 默认 `timeout=10s`。浏览器 UI 选会话/加载/发送可能超过 10 秒，若阻塞等待会被 LangBot 判定发送失败并重试，表现为“切换两次才发出”。

## 2. 前置条件

- macOS/Windows/Linux 均可（当前仓库以 macOS 路径为主）
- 已安装 Google Chrome
- Python 3.10+（建议 3.11/3.12）
- LangBot 已能正常运行（可在宿主机或 Docker）

## 3. 启动 wechat-auto-reply（v2 网关）

在本仓库目录执行：

```bash
./start_wechat_auto_v2.sh install
./start_wechat_auto_v2.sh start
```

也可以用统一入口：

```bash
./start.sh v2
```

首次启动会打开 Chrome 并进入 `https://wx.qq.com/`，用手机微信扫码登录。

常用命令：

- `./start_wechat_auto_v2.sh restart`：建议首选。会杀掉占用该 profile 的残留 Chrome 进程，解决 “Chrome instance exited / session not created”等问题。
- 健康检查：
  - `curl http://127.0.0.1:8059/health`
  - `curl http://127.0.0.1:8088/ws/health`

配置文件（建议按需修改）：

- `wechat_auto_service_v2/config.json`
  - `bot.wxid`：与 LangBot 配置保持一致（Selenium 模式下无法稳定获得真实 wxid，因此用约定值）
  - `web_monitor.contact_blacklist / whitelist`：联系人过滤
  - `web_monitor.group_mention_required`：群聊是否必须 @ 才回复（推荐开启，避免群里“乱回”）
  - `web_monitor.bot_group_nickname`：群里机器人展示昵称（用于识别 @）
  - `merge.window_sec`：合并短时间多条消息（降低 LLM 调用次数，但会增加一点延迟）

## 4. 配置 LangBot（使用内置 wechat08）

LangBot 内置 `wechat08` 平台适配器会：
- 连接 WebSocket 接收消息
- 调用 HTTP `SendTxt` 发送回复

你只需要把下面两个地址配置正确：

### 4.1 LangBot 运行在宿主机（与网关同机）

- `wechat08_api_base`: `http://127.0.0.1:8059/api`
- `wechat08_ws_base`: `ws://127.0.0.1:8088/ws`

### 4.2 LangBot 运行在 Docker（最常见）

容器内访问宿主机服务应使用 `host.docker.internal`：

- `wechat08_api_base`: `http://host.docker.internal:8059/api`
- `wechat08_ws_base`: `ws://host.docker.internal:8088/ws`

注意：
- 网关服务端监听 `0.0.0.0` 是为了“可被容器访问”；客户端连接时不要写 `0.0.0.0`，应写 `127.0.0.1` 或 `host.docker.internal`。

## 5. 联调检查清单（按顺序）

1. 网关是否启动成功（日志 `logs/wechat_auto_v2.out`）：
   - 有 `WeChat automation started.`
   - 有 `Uvicorn running on http://0.0.0.0:8059` 与 `:8088`
2. LangBot 是否能连上 WS：
   - 若出现 `Connection refused`：通常是地址写错（容器内用了 `127.0.0.1`）或端口未开放
3. 新消息是否被推送到 LangBot：
   - 在网关日志里可看到 `📨 收到来自 ... 的消息`
4. LangBot 是否调了 `SendTxt`：
   - 在网关日志里可看到 `wechat08 SendTxt: to=...`

## 6. 常见问题排查

### 6.1 LangBot 报 `Read timed out (read timeout=10.0)`

这是 LangBot 默认 10 秒 HTTP 超时导致的。网关现已把 `/api/Msg/SendTxt` 改为“入队即返回”，通常不再触发超时。

### 6.2 网关返回 `503 automation not ready`

说明 Selenium 自动化没跑起来（Chrome/driver 未启动或启动失败），你需要：

1) `./start_wechat_auto_v2.sh restart`
2) 查看 `logs/wechat_auto_v2.out` 是否有 `session not created` / `Chrome instance exited`

### 6.3 “监控突然没了 / 不点会话 / 不回复”

网页端偶发弹窗（例如插件提示）会阻塞 Selenium。网关已加入弹窗自动 dismiss 逻辑；如果仍发生，直接：

`./start_wechat_auto_v2.sh restart`

或者：

`./start.sh restart-v2`

### 6.4 回复慢、需要切换多次才发出

浏览器自动化本质上受 UI 加载影响。可调整：

- `wechat_auto_service_v2/config.json`：
  - `web_monitor.check_interval`（建议 1）
  - `merge.window_sec`（想更快就调小，例如 0.3~0.5）

## 7. 发送任务状态（调试用）

`SendTxt` 会返回 `jobId`（网关内部发送任务）。可用以下接口查看任务是否已完成：

- `GET /api/Msg/SendTxtStatus?jobId=1`

> 注意：这是调试接口；LangBot 本身不依赖该接口。

## 8. 合规与风险说明

- 本项目通过网页端 UI 自动化完成收发消息，**不涉及协议逆向**，在工程说明与合规沟通中通常更容易阐述实现路径。
- 但本项目仍然属于非官方自动化工具，请确保用途与内容符合微信及企业相关制度与法律法规。
