# V1（Legacy）详细说明：本地浏览器自动回复 + 直连 LLM

V1 是本仓库早期版本：**Selenium 控制网页微信 `wx.qq.com`** 监控消息，并在本地直接调用 LLM 生成回复后再通过浏览器发送出去。

> 如果你需要与 LangBot 配合，请优先使用 V2：`wechat_auto_service_v2/`（wechat08 兼容网关）。V1 不提供 wechat08 网关协议。

## 1. V1 的优势 ✅

- **单机即可运行**：不依赖额外网关/机器人系统，配置好 LLM 后即可本地自动回复。
- **实现简单直观**：一套程序完成“监控 → 生成回复 → 发送”闭环，便于快速验证效果。
- **仍然是浏览器路径**：收发消息都来自网页微信 UI/DOM（不是协议逆向）。

## 2. V1 的局限 ⚠️

- **强耦合 LLM**：回复逻辑与 LLM 绑定在本项目，难以接入复杂机器人流水线（插件、记忆、工具调用等）。
- **可靠性受 UI 影响**：网页结构变化、弹窗、页面卡顿都可能导致监控/发送不稳定。
- **部署形态不利于服务化**：更适合个人电脑常驻，不适合多实例扩展与统一管理。

## 3. V1 项目结构

```
.
├── main.py                # V1 入口：启动 Selenium + 直连 LLM 自动回复
├── config.example.json    # V1 配置模板（不会包含密钥）
├── config.json            # 你的本地配置（建议不要提交）
├── modules/
│   ├── web_monitor.py     # 网页微信监控与发送（Selenium）
│   ├── ai_model.py        # OpenAI compatible LLM 调用封装
│   ├── config.py          # 配置读取
│   └── logger.py          # 日志
├── requirements.txt
└── start_wechat_auto_v1.sh # V1 一键启动脚本
```

## 4. 配置说明（V1）

V1 优先读取环境变量 `AI_API_KEY`，若未设置才会尝试读取 `config.json` 里的 `ai_model.api_key`。

建议做法（更安全）：

```bash
export AI_API_KEY="YOUR_KEY"
```

然后复制配置模板：

```bash
cp config.example.json config.json
```

你主要会修改：

- `ai_model.api_url` / `ai_model.model_name` / `ai_model.system_prompt`
- `web_monitor.contact_blacklist` / `web_monitor.contact_whitelist`
- `web_monitor.group_mention_required` / `web_monitor.bot_group_nickname`

## 5. 一键启动（V1）

```bash
./start_wechat_auto_v1.sh install
./start_wechat_auto_v1.sh start
```

如果 Chrome profile 被占用、或出现 “Chrome instance exited / session not created”，用：

```bash
./start_wechat_auto_v1.sh restart
```

## 6. 旧版与 V2 的选择建议

- 你想 **快速本地自回复** → 用 V1
- 你想 **接 LangBot / 更服务化 / 更可控** → 用 V2（推荐）
