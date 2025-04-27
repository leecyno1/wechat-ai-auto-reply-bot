from modules.config import Config
import json

# 加载配置
config = Config('config.json')
print("Config loaded.")

# 打印web_monitor配置内容
print("="*50)
print("WEB MONITOR CONFIG:")
print(json.dumps(config.config.get('web_monitor', {}), indent=2, ensure_ascii=False))
print("="*50)

# 特别检查login_success_selector
login_selector = config.get('web_monitor', 'login_success_selector', '.unknown')
print(f"Login Success Selector: {login_selector}") 