# 微信 AI 自动记录回复机器人 (WeChat AI Auto-Reply & Logger Bot) 🤖

[English Version](#english-version)

一个使用浏览器自动化和大型语言模型 (LLM) 来自动回复微信消息，并能分类记录和总结聊天内容的 Python 机器人。

## ✨ 功能特性

*   **自动登录**: 通过扫描二维码自动登录网页版微信。
*   **消息监控**: 实时监控指定联系人或群聊的新消息。
*   **智能回复**:
    *   利用配置的 LLM API (如 OpenAI, SiliconFlow 等) 生成回复。
    *   可配置仅回复提及自己的群消息或特定关键词触发的消息。
    *   可配置联系人白名单或黑名单。
*   **聊天记录**: 将收到的消息和机器人的回复记录到日志文件 (`logs/chats/chat_YYYYMMDD.json`)。
*   **记录导出与总结**:
    *   运行 `export_logs.py` 脚本。
    *   根据关键词将日志分类（如路演信息、调研预约、观点讨论等）。
    *   调用 LLM API 对指定分类的聊天记录进行总结。
    *   将分类后的完整记录和总结导出到 Excel 文件 (`chat_log_export.xlsx`)。

## ⚙️ 设置步骤

1.  **克隆仓库**:
    ```bash
    git clone https://github.com/YOUR_USERNAME/wechat-ai-auto-reply-bot.git # 请替换 YOUR_USERNAME
    cd wechat-ai-auto-reply-bot
    ```

2.  **创建并激活虚拟环境**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate  # Linux/macOS
    # .\\.venv\\Scripts\\activate  # Windows
    ```

3.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **配置环境变量**:
    创建 `.env` 文件 (可以复制 `.env.example` 并修改)，并设置以下变量：
    *   `AI_API_KEY`: 你的 LLM API 密钥 (例如 OpenAI 或 SiliconFlow 的 key)。

5.  **修改配置文件 (`config.json`)**:
    *   检查并根据需要修改 `web_monitor` 部分的配置，如联系人黑白名单 (`contact_blacklist`, `contact_whitelist`)、触发关键词 (`trigger_keywords`) 等。
    *   检查并修改 `ai_model` 部分，确保 `api_url`, `model_name` 等设置正确。**API Key 已通过环境变量设置，无需在此处填写。**
    *   检查并修改 `export` 部分的关键词 (`roadshow_keywords`, `appointment_keywords`, `opinion_keywords`) 和总结提示词 (`summarize_prompt_template`)。

## 🚀 使用方法

### 运行主机器人

```bash
python main.py
```

*   脚本会尝试打开浏览器并显示二维码，请使用手机微信扫描登录。
*   登录成功后，机器人会开始监控消息并根据配置进行回复和记录。

### 运行记录导出和总结脚本

```bash
python export_logs.py
```

*   脚本会读取 `logs/chats/` 目录下的所有 `.json` 日志文件。
*   进行分类、总结，并将结果保存到项目根目录下的 `chat_log_export.xlsx` 文件。

## 📄 依赖

主要依赖库见 `requirements.txt` 文件，包括:
*   `selenium`: 浏览器自动化。
*   `webdriver-manager`: 自动管理浏览器驱动。
*   `requests`: 发送 HTTP 请求 (用于调用 LLM API)。
*   `pandas`: 处理数据和导出 Excel。
*   `openpyxl`: 读写 Excel 文件。

---

# English Version

A Python bot using browser automation and Large Language Models (LLMs) to auto-reply to WeChat messages and categorize, log, and summarize chat contents.

## ✨ Features

*   **Auto Login**: Automatically logs into WeChat Web by scanning a QR code.
*   **Message Monitoring**: Monitors new messages from specified contacts or group chats in real-time.
*   **Intelligent Replies**:
    *   Generates replies using a configured LLM API (e.g., OpenAI, SiliconFlow).
    *   Configurable to reply only to messages mentioning oneself in groups or triggered by specific keywords.
    *   Configurable contact whitelist or blacklist.
*   **Chat Logging**: Logs received messages and the bot's replies to log files (`logs/chats/chat_YYYYMMDD.json`).
*   **Log Export & Summarization**:
    *   Run the `export_logs.py` script.
    *   Categorizes logs based on keywords (e.g., roadshow info, appointment requests, opinions).
    *   Calls the LLM API to summarize chat records for specified categories.
    *   Exports the categorized full log and summaries to an Excel file (`chat_log_export.xlsx`).

## ⚙️ Setup Instructions

1.  **Clone the Repository**:
    ```bash
    git clone https://github.com/YOUR_USERNAME/wechat-ai-auto-reply-bot.git # Replace YOUR_USERNAME
    cd wechat-ai-auto-reply-bot
    ```

2.  **Create and Activate Virtual Environment**:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate  # Linux/macOS
    # .\\.venv\\Scripts\\activate  # Windows
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables**:
    Create a `.env` file (you can copy `.env.example` and modify it) and set the following variable:
    *   `AI_API_KEY`: Your LLM API key (e.g., key for OpenAI or SiliconFlow).

5.  **Modify Configuration File (`config.json`)**:
    *   Review and modify the `web_monitor` section as needed, such as contact lists (`contact_blacklist`, `contact_whitelist`), trigger keywords (`trigger_keywords`), etc.
    *   Review and modify the `ai_model` section, ensuring `api_url`, `model_name`, etc., are correct. **The API Key is set via environment variable and should not be filled here.**
    *   Review and modify the `export` section's keywords (`roadshow_keywords`, `appointment_keywords`, `opinion_keywords`) and summary prompt (`summarize_prompt_template`).

## 🚀 Usage

### Running the Main Bot

```bash
python main.py
```

*   The script will attempt to open a browser and display a QR code. Scan it with your mobile WeChat to log in.
*   Once logged in, the bot will start monitoring messages and replying/logging according to the configuration.

### Running the Log Export and Summarization Script

```bash
python export_logs.py
```

*   The script reads all `.json` log files from the `logs/chats/` directory.
*   It categorizes, summarizes, and saves the results to `chat_log_export.xlsx` in the project root directory.

## 📄 Dependencies

Key dependencies are listed in `requirements.txt`, including:
*   `selenium`: Browser automation.
*   `webdriver-manager`: Automatic browser driver management.
*   `requests`: Making HTTP requests (for LLM API calls).
*   `pandas`: Data manipulation and Excel export.
*   `openpyxl`: Reading/writing Excel files.
