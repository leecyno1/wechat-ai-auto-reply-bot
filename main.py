import time
from modules.config import Config
from modules.logger import Logger
from modules.ai_model import AIModel
from modules.web_monitor import WebMonitor
import os
from pathlib import Path
import shutil

def main():
    """主程序入口"""
    logger_instance = None # Define logger outside try block for finally
    web_monitor = None # Define web_monitor outside try block for finally
    
    try:
        # 加载配置（优先使用本地 config.json；若不存在则从模板生成）
        cfg_path = Path("config.json")
        if not cfg_path.exists():
            example = Path("config.example.json")
            if example.exists():
                shutil.copyfile(str(example), str(cfg_path))
                print("Created config.json from config.example.json (please review and edit as needed).")
            else:
                raise FileNotFoundError("Missing config.json (and config.example.json not found).")

        config = Config(str(cfg_path))
        # 初始化日志记录器
        # Pass the specific logger config section
        logger_config = config.get('logger') 
        logger_instance = Logger(logger_config)
        logger_instance.info("====== 系统启动 ======")
        
        # 初始化AI模型
        # Pass the specific AI model config section
        ai_config = config.get('ai_model')
        ai_model = AIModel(logger_instance, ai_config)
        logger_instance.info(f"AI 模型 ('{ai_config.get('model_type')}') 初始化.")
        
        # 初始化网页监测器
        # Pass the specific web monitor config section
        monitor_config = config.get('web_monitor')
        web_monitor = WebMonitor(logger_instance, ai_model, monitor_config)
        
        # 初始化浏览器驱动并登录
        if web_monitor.initialize():
            logger_instance.info("浏览器初始化和登录成功。")
            logger_instance.info("开始监控消息循环...")
            web_monitor.monitor_messages()  # 启动消息监控 (blocking loop)
        else:
            logger_instance.error("Web Monitor 初始化失败，程序将退出。")
            
    except KeyboardInterrupt:
        if logger_instance: logger_instance.info("用户请求中断 (Ctrl+C)..." )
        else: print("用户请求中断 (Ctrl+C)...")
    except Exception as e:
        if logger_instance: logger_instance.error(f"主程序发生未处理的异常: {str(e)}", exc_info=True)
        else: print(f"主程序发生未处理的异常: {str(e)}")
    finally:
        # 关闭资源
        if web_monitor:
            web_monitor.close()
        if logger_instance: logger_instance.info("====== 系统关闭 ======")
        else: print("System shutdown.")

if __name__ == "__main__":
    main()
