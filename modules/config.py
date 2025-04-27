import json
import os

class Config:
    def __init__(self, config_file='config.json'):
        self.config_file = config_file
        self.config = self.load_config()
        
    def load_config(self):
        """加载配置文件"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"加载配置文件时出错: {str(e)}")
                return self.get_default_config()
        else:
            # 创建默认配置
            config = self.get_default_config()
            self.save_config(config)
            return config
    
    def get_default_config(self):
        """获取默认配置"""
        return {
            "web_monitor": {
                "check_interval": 3,  # 消息检查间隔（秒）
                "auto_reply_all": False,  # 是否自动回复所有消息
                # VERIFY These Selectors with DevTools!
                "login_success_selector": ".main", # Element indicating successful login
                "unread_msg_selector": ".chat_item.slide-left.ng-scope", # Selector for unread chat items
                "last_message_selector": ".message.ng-scope", # Selector for messages in chat
                "received_message_content_selector": ".js_message_plain", # Selector for text in received message
                "input_box_selector": ".editArea", # Selector for the chat input box
            },
            "ai_model": {
                "model_type": "openai",  # 模型类型：openai, baidu, etc.
                "api_key": "YOUR_OPENAI_API_KEY_HERE",  # API密钥
                "api_url": "https://api.openai.com/v1/chat/completions",  # API地址
                "model_name": "gpt-3.5-turbo",  # 模型名称
                "system_prompt": "你是一个友好的助手，请简洁地回答问题。",  # 系统提示词
                "max_tokens": 150,  # 最大令牌数
                "temperature": 0.7,  # 温度参数
                "baidu_client_id": "YOUR_BAIDU_CLIENT_ID_HERE",
                "baidu_client_secret": "YOUR_BAIDU_CLIENT_SECRET_HERE",
                "baidu_api_url": "https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions" # Example URL for Baidu
            },
            "logger": {
                "log_dir": "logs",  # 日志目录
                "log_level": "INFO"  # 日志级别
            }
        }
    
    def save_config(self, config=None):
        """保存配置到文件"""
        if config is None:
            config = self.config
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"保存配置文件时出错: {str(e)}")
            return False
    
    def get(self, section, key=None, default=None):
        """获取配置项"""
        if key is None:
            # 确保 self.config 是字典
            if not isinstance(self.config, dict):
                print(f"Error: self.config is not a dictionary! Type: {type(self.config)}")
                return default if default is not None else {}
            # section 是键 (string)
            return self.config.get(section, default if default is not None else {})
        else:
            # 确保 self.config 是字典
            if not isinstance(self.config, dict):
                 print(f"Error: self.config is not a dictionary! Type: {type(self.config)}")
                 return default
            # section 是键 (string)
            section_data = self.config.get(section, {})
            # 确保 section_data 是字典
            if not isinstance(section_data, dict):
                 print(f"Error: Section '{section}' data is not a dictionary! Type: {type(section_data)}")
                 return default
            # 确保 key 是可哈希的 (虽然这里 key 应该是 string)
            try:
                 hash(key)
            except TypeError:
                 print(f"Error: Key '{key}' is not hashable! Type: {type(key)}")
                 return default

            # key 是键 (string)
            return section_data.get(key, default)
    
    def update(self, section, key, value):
        """更新配置项"""
        if section not in self.config:
            self.config[section] = {}
        
        self.config[section][key] = value
        return self.save_config()
