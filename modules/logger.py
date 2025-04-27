import logging
import os
import json
from datetime import datetime

class Logger:
    def __init__(self, config):
        self.config = config if isinstance(config, dict) else {} # Ensure config is a dict
        self.setup_logger()
        self.chat_log_file = self.setup_chat_log()
        
    def setup_logger(self):
        """设置系统日志"""
        log_dir = self.config.get('log_dir', 'logs')
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
            except OSError as e:
                 print(f"Error creating log directory {log_dir}: {e}")
                 log_dir = "." # Fallback to current directory
        
        log_file = os.path.join(log_dir, f"system_{datetime.now().strftime('%Y%m%d')}.log")
        
        # 创建日志记录器
        self.logger = logging.getLogger('wechat_bot')
        self.logger.setLevel(self.config.get('log_level', 'INFO').upper()) # Use config level

        # 防止重复添加 handlers
        if not self.logger.handlers:
            # 创建文件处理器
            try:
                file_handler = logging.FileHandler(log_file, encoding='utf-8')
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
        
    def setup_chat_log(self):
        """设置聊天日志文件"""
        log_dir = self.config.get('log_dir', 'logs')
        chat_log_dir = os.path.join(log_dir, 'chats')
        if not os.path.exists(chat_log_dir):
            try:
                os.makedirs(chat_log_dir)
            except OSError as e:
                print(f"Error creating chat log directory {chat_log_dir}: {e}")
                chat_log_dir = "." # Fallback
            
        return os.path.join(chat_log_dir, f"chat_{datetime.now().strftime('%Y%m%d')}.json")
    
    def log_chat(self, message, reply):
        """记录聊天消息和回复"""
        try:
            chat_entry = {
                "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "message": message,
                "reply": reply
            }
            
            # 加载已有聊天记录
            chat_history = []
            if os.path.exists(self.chat_log_file):
                # Check if file is not empty before loading
                if os.path.getsize(self.chat_log_file) > 0:
                    with open(self.chat_log_file, 'r', encoding='utf-8') as f:
                        try:
                            chat_history = json.load(f)
                            # Ensure it's a list
                            if not isinstance(chat_history, list):
                                chat_history = []
                        except json.JSONDecodeError:
                            self.error(f"Chat log file {self.chat_log_file} is corrupted. Starting new log.")
                            chat_history = []
                else:
                     chat_history = [] # File exists but is empty
            
            # 添加新的聊天记录
            chat_history.append(chat_entry)
            
            # 保存更新后的聊天记录
            with open(self.chat_log_file, 'w', encoding='utf-8') as f:
                json.dump(chat_history, f, ensure_ascii=False, indent=4)
                
            self.info(f"已记录聊天: {message[:20]}...")
        except Exception as e:
            self.error(f"记录聊天时出错: {str(e)}")
    
    # 代理日志方法
    def info(self, message):
        self.logger.info(message)
        
    def error(self, message, exc_info=False):
        # Pass exc_info to the underlying logger
        self.logger.error(message, exc_info=exc_info)
        
    def warning(self, message):
        self.logger.warning(message)
        
    def debug(self, message):
        self.logger.debug(message)
