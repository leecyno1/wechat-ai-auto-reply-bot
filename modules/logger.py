import logging
import os
import json
from datetime import datetime
import logging.handlers # Import handlers

class Logger:
    def __init__(self, config):
        self.config = config if isinstance(config, dict) else {} # Ensure config is a dict
        self.logger = None # Initialize logger attribute
        self.current_chat_log_file = None
        self.current_chat_week_str = None # Stores the current week string (e.g., '2023-45')
        self.chat_log_dir = self._ensure_chat_log_dir()
        self.setup_logger() # Setup system logger first
        # Removed self.chat_log_file setup from here, it will be dynamic
        
    def setup_logger(self):
        """设置系统日志 (使用固定文件名并覆盖)"""
        log_dir = self.config.get('log_dir', 'logs')
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError as e:
                 print(f"Error creating log directory {log_dir}: {e}")
                 log_dir = "." # Fallback to current directory
        
        # Use a fixed filename for the system log
        log_file = os.path.join(log_dir, "system.log") 
        
        # 创建日志记录器
        self.logger = logging.getLogger('wechat_bot')
        self.logger.setLevel(self.config.get('log_level', 'INFO').upper()) # Use config level

        # 防止重复添加 handlers
        if not self.logger.handlers:
            # 创建文件处理器 - 使用 mode='w' 来覆盖
            try:
                # Use mode='w' to overwrite the log file each time the logger is set up (i.e., on script start)
                file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8') 
                file_handler.setLevel(self.config.get('log_level', 'INFO').upper())
            except Exception as e:
                print(f"Error creating file handler {log_file}: {e}")
                file_handler = None
            
            # 创建控制台处理器
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.config.get('log_level', 'INFO').upper())
            
            # 创建格式化器
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            if file_handler: file_handler.setFormatter(formatter)
            console_handler.setFormatter(formatter)
            
            # 添加处理器到记录器
            if file_handler: self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)
        
    def _ensure_chat_log_dir(self):
        """确保聊天日志目录存在并返回其路径"""
        log_dir = self.config.get('log_dir', 'logs')
        chat_log_dir = os.path.join(log_dir, 'chats')
        if not os.path.exists(chat_log_dir):
            try:
                os.makedirs(chat_log_dir)
            except OSError as e:
                # Use self.logger if available, otherwise print
                msg = f"Error creating chat log directory {chat_log_dir}: {e}"
                if self.logger:
                    self.logger.error(msg)
                else:
                    print(msg)
                chat_log_dir = "." # Fallback
        return chat_log_dir

    def _get_current_chat_log_file(self):
        """获取当前周的聊天日志文件路径，如果周数变化则更新"""
        now = datetime.now()
        # 使用 %W 将周一作为一周的开始 (00-53)
        # 使用 %Y-%W 格式确保年份正确处理跨年周
        current_week_str = now.strftime("%Y-%W") 
        
        if current_week_str != self.current_chat_week_str:
            self.info(f"New week detected ({current_week_str}). Setting chat log file.")
            self.current_chat_week_str = current_week_str
            # Generate the new weekly filename
            self.current_chat_log_file = os.path.join(self.chat_log_dir, f"chat_{current_week_str}.json")
            self.info(f"Chat log file for this week: {self.current_chat_log_file}")
            
        # 如果 current_chat_log_file 尚未初始化 (首次调用)
        if self.current_chat_log_file is None:
             self.current_chat_log_file = os.path.join(self.chat_log_dir, f"chat_{current_week_str}.json")
             self.info(f"Initial chat log file set to: {self.current_chat_log_file}")
             
        return self.current_chat_log_file
    
    def log_chat(self, message, reply):
        """记录聊天消息和回复到当前周的日志文件"""
        try:
            # Get the correct log file path for the current week
            chat_log_file_path = self._get_current_chat_log_file()
            
            chat_entry = {
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "message": message,
                "reply": reply
            }
            
            # 加载已有聊天记录 (从当前周的文件)
            chat_history = []
            if os.path.exists(chat_log_file_path):
                # Check if file is not empty before loading
                if os.path.getsize(chat_log_file_path) > 0:
                    try:
                        with open(chat_log_file_path, 'r', encoding='utf-8') as f:
                            chat_history = json.load(f)
                        # Ensure it's a list
                        if not isinstance(chat_history, list):
                             self.warning(f"Chat log file {chat_log_file_path} content is not a list. Resetting.")
                             chat_history = []
                    except json.JSONDecodeError:
                        self.error(f"Chat log file {chat_log_file_path} is corrupted. Starting new log for this entry.")
                        chat_history = []
                    except Exception as read_err:
                         self.error(f"Error reading chat log file {chat_log_file_path}: {read_err}")
                         chat_history = [] # Proceed with caution, starting fresh for this entry
                else:
                     chat_history = [] # File exists but is empty
            
            # 添加新的聊天记录
            chat_history.append(chat_entry)
            
            # 保存更新后的聊天记录 (到当前周的文件)
            with open(chat_log_file_path, 'w', encoding='utf-8') as f:
                json.dump(chat_history, f, ensure_ascii=False, indent=4)
                
            # self.info(f"已记录聊天: {message[:20]}...") # Avoid excessive logging for every chat message
        except Exception as e:
            self.error(f"记录聊天时出错: {str(e)}", exc_info=True)
    
    # 代理日志方法
    def info(self, message):
        if self.logger: # Ensure logger is initialized
             self.logger.info(message)
        else:
             print(f"INFO: {message}") # Fallback if logger setup failed
        
    def error(self, message, exc_info=False):
        if self.logger:
             # Pass exc_info to the underlying logger
             self.logger.error(message, exc_info=exc_info)
        else:
             print(f"ERROR: {message}")
        
    def warning(self, message):
         if self.logger:
              self.logger.warning(message)
         else:
              print(f"WARNING: {message}")
        
    def debug(self, message):
         if self.logger:
              self.logger.debug(message)
         else:
              # Optionally print debug if logger isn't ready
              # print(f"DEBUG: {message}") 
              pass 
