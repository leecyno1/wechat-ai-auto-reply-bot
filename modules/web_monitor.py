from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
import time
import os # Import os module

class WebMonitor:
    def __init__(self, logger, ai_model, config):
        self.logger = logger
        self.ai_model = ai_model
        self.config = config # This should be the web_monitor section of the config
        self.driver = None
        # Selectors from config (provide defaults if not found)
        self.login_success_selector = self.config.get('login_success_selector', '.main')
        self.logger.info(f"从配置中读取login_success_selector: {self.login_success_selector}")
        self.unread_msg_selector = self.config.get('unread_msg_selector', '.chat_item:has(.web_wechat_reddot_middle)') # Needs verification!
        self.active_chat_selector = self.config.get('active_chat_selector', '.chat_item.active') # Needs verification!
        self.contact_name_in_list_selector = '.nickname .nickname_text' # Used for both unread and active - VERIFY
        self.last_message_selector = self.config.get('last_message_selector', '.message.ng-scope') # Needs verification!
        self.received_message_content_selector = self.config.get('received_message_content_selector', '.js_message_plain') # Needs verification!
        self.input_box_selector = self.config.get('input_box_selector', '#editArea') # Needs verification!
        self.processed_message_signatures = set() # To avoid processing the same message multiple times
        self.trigger_keywords = self.config.get('trigger_keywords', [])
        # self.ignored_contacts = self.config.get('ignored_contacts', []) # Replaced by blacklist/whitelist
        # New list mode settings
        self.contact_list_mode = self.config.get('contact_list_mode', 'blacklist').lower()
        self.contact_whitelist = self.config.get('contact_whitelist', [])
        self.contact_blacklist = self.config.get('contact_blacklist', [])
        self.group_mention_required = self.config.get('group_mention_required', True)
        self.bot_group_nickname = self.config.get('bot_group_nickname', '机器人小助手botAI')
        self.group_chat_indicators = self.config.get('group_chat_indicators', []) # For future group detection
        # Load user data dir config and use it directly
        self.user_data_dir_config = self.config.get('user_data_dir', 'wechat_user_data_bot')
        # Construct absolute path directly from the config value
        self.user_data_dir_path = os.path.abspath(self.user_data_dir_config)

        if self.contact_list_mode not in ["blacklist", "whitelist"]:
            self.logger.warning(f"Invalid contact_list_mode '{self.contact_list_mode}', defaulting to blacklist.")
            self.contact_list_mode = "blacklist"
        self.logger.info(f"Contact list mode: {self.contact_list_mode}")
        if self.contact_list_mode == 'whitelist':
            self.logger.info(f"Whitelist: {self.contact_whitelist}")
        else:
            self.logger.info(f"Blacklist: {self.contact_blacklist}")
        self.logger.info(f"Using user data directory: {self.user_data_dir_path}")

    def initialize(self):
        """初始化浏览器驱动并打开微信网页版 (支持持久化登录)"""
        try:
            self.logger.info("Initializing Chrome WebDriver...")
            options = webdriver.ChromeOptions()
            options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36")
            options.add_argument('--window-size=1280,800')
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            # Add user data directory argument
            options.add_argument(f'--user-data-dir={self.user_data_dir_path}')

            service = ChromeService(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.driver.implicitly_wait(5)
            self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': '''Object.defineProperty(navigator, 'webdriver', {get: () => undefined})'''
            })
            
            self.logger.info("Navigating to WeChat Web...")
            self.driver.get('https://wx.qq.com/')

            # --- Check for existing login first --- 
            self.logger.info(f"Checking for existing login session using selector: {self.login_success_selector}")
            try:
                # Use a short wait time to quickly check if already logged in
                short_wait = WebDriverWait(self.driver, 5)
                short_wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, self.login_success_selector))
                )
                self.logger.info("检测到已存在的登录会话！")
                return True # Already logged in
            except TimeoutException:
                self.logger.info("未检测到登录会话，需要扫描二维码。")
                # --- Proceed with QR code login flow --- 
                self.logger.info("请使用微信扫描二维码登录")
                try:
                    long_wait = WebDriverWait(self.driver, 120) # Keep long wait for manual scan
                    long_wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, self.login_success_selector))
                    )
                    self.logger.info("扫码登录成功")
                    return True
                except TimeoutException:
                    self.logger.error(f"登录超时: 未能在120秒内检测到登录成功标识 '{self.login_success_selector}'. 请确保选择器正确并且已登录。")
                    self.close()
                    return False
                except Exception as qr_login_err:
                     self.logger.error(f"扫描登录过程中出错: {str(qr_login_err)}")
                     self.close()
                     return False

        except Exception as e:
            self.logger.error(f"初始化或登录检查失败: {str(e)}", exc_info=True)
            self.close()
            return False
    
    def monitor_messages(self):
        """监控新消息 (优先处理红点，再检查活跃聊天)"""
        check_interval = self.config.get('check_interval', 3)
        self.logger.info(f"开始监控新消息，检查间隔: {check_interval}秒")
        self.logger.info(f"触发关键词: {self.trigger_keywords if self.trigger_keywords else '[无 (回复所有)]'}")
        if self.contact_list_mode == 'whitelist':
            self.logger.info(f"白名单模式，仅回复: {self.contact_whitelist}")
        else:
            self.logger.info(f"黑名单模式，忽略: {self.contact_blacklist}")

        while True:
            processed_in_cycle = False
            try:
                # 检查浏览器是否仍然活跃
                if not self.is_browser_alive():
                     self.logger.error("浏览器似乎已关闭或无响应，停止监控。")
                     break

                # --- 1. 查找并处理带红点的未读聊天 ---
                unread_chat_items = []
                try:
                    # Use the potentially more precise selector from config
                    unread_chat_items = self.driver.find_elements(By.CSS_SELECTOR, self.unread_msg_selector)
                except Exception as find_err:
                     self.logger.error(f"查找未读聊天项 ({self.unread_msg_selector}) 时出错: {find_err}")

                if unread_chat_items:
                    self.logger.info(f"发现 {len(unread_chat_items)} 个带未读标记的聊天项 (选择器: {self.unread_msg_selector})")
                    msg_item = unread_chat_items[0] # Process first one
                    if self.process_chat_item(msg_item): # Returns True if processed
                        processed_in_cycle = True
                        time.sleep(1) # Short delay after processing one item
                        continue # Restart loop to prioritize next unread

                # --- 2. 如果没有红点项被处理，检查活跃聊天窗口 --- 
                if not processed_in_cycle:
                    try:
                        active_chat_element = self.driver.find_element(By.CSS_SELECTOR, self.active_chat_selector)
                        self.logger.debug(f"检查活跃聊天窗口 (选择器: {self.active_chat_selector})")
                        if self.process_chat_item(active_chat_element, check_only_new=True): # Pass flag to only check new
                            processed_in_cycle = True
                    except NoSuchElementException:
                        self.logger.debug("当前无活跃聊天窗口或选择器无效。")
                    except Exception as active_err:
                        self.logger.error(f"检查活跃聊天 ({self.active_chat_selector}) 时出错: {active_err}")

                # --- 3. 等待下次检查 ---
                # self.logger.debug("完成检查周期，等待...")
                time.sleep(check_interval)

            except KeyboardInterrupt:
                raise
            except Exception as e:
                self.logger.error(f"监控消息主循环出错: {str(e)}")
                self.logger.info("发生错误，等待10秒后重试...")
                time.sleep(10)

    def is_browser_alive(self):
        """检查浏览器是否仍在运行"""
        try:
            # Accessing driver.title or current_url should raise an error if browser/session is closed
            _ = self.driver.title 
            return True
        except Exception as e:
            self.logger.warning(f"检查浏览器状态时出错 (可能已关闭): {e}")
            return False

    def process_chat_item(self, chat_item_element, check_only_new=False):
        """
        处理单个聊天项（无论是带红点还是活跃状态）。
        :param chat_item_element: The WebElement for the chat item.
        :param check_only_new: If True, only process if the last message is newer than the recorded one.
        :return: True if a message was processed (reply attempted), False otherwise.
        """
        contact_name = "Unknown"
        try:
            contact_name_element = chat_item_element.find_element(By.CSS_SELECTOR, self.contact_name_in_list_selector)
            contact_name = contact_name_element.text.strip()

            # --- Blacklist/Whitelist Check --- 
            if self.contact_list_mode == "whitelist":
                if contact_name not in self.contact_whitelist:
                    self.logger.info(f"联系人 '{contact_name}' 不在白名单中，跳过。")
                    return False
            elif self.contact_list_mode == "blacklist": # Default mode
                 if contact_name in self.contact_blacklist:
                    self.logger.info(f"联系人 '{contact_name}' 在黑名单中，跳过。")
                    return False
            # --- End Blacklist/Whitelist Check --- 
            
            self.logger.info(f"检查来自 '{contact_name}' 的聊天 (仅新消息: {check_only_new}) ")
            
            # 如果不是活跃聊天检查，点击它
            if not check_only_new:
                 self.logger.info(f"点击聊天项: '{contact_name}'")
                 try:
                    chat_item_element.click()
                    time.sleep(1.5) # Wait for chat to potentially load
                 except Exception as click_err:
                     self.logger.error(f"点击聊天项 '{contact_name}' 时出错: {click_err}")
                     return False # Could not process

            # 获取最后一条接收到的消息
            last_message_text = self.get_last_received_message(contact_name)

            if last_message_text:
                message_signature = f"{contact_name}::{last_message_text}"
                if message_signature in self.processed_message_signatures:
                    if check_only_new:
                         self.logger.debug(f"活跃聊天 '{contact_name}' 的最后消息已处理过。")
                    else: 
                         self.logger.info(f"消息已处理过: {message_signature[:50]}...")
                    return False # Not processed in this instance

                # 新消息!
                self.logger.info(f"从 '{contact_name}' 获取到新消息: {last_message_text[:50]}...")
                self.processed_message_signatures.add(message_signature)
                if len(self.processed_message_signatures) > 1000: # Limit cache size
                    self.processed_message_signatures.pop()
                
                # --- Group Mention Check (Placeholder) --- 
                # TODO: Implement actual group chat detection based on selectors/indicators
                is_group = self.detect_if_group_chat(chat_item_element, contact_name) 
                if is_group and self.group_mention_required:
                    mention_tag = f"@{self.bot_group_nickname}"
                    if mention_tag not in last_message_text:
                         self.logger.info(f"群聊消息未 @{self.bot_group_nickname}，跳过回复。")
                         return False # Processed signature but didn't reply
                    else:
                         self.logger.info(f"群聊消息检测到 @{self.bot_group_nickname}。")
                # --- End Group Mention Check --- 

                # --- Keyword Check --- 
                triggered = False
                if not self.trigger_keywords:
                    triggered = True
                else:
                    for keyword in self.trigger_keywords:
                        if keyword in last_message_text:
                            self.logger.info(f"消息包含关键词 '{keyword}'，触发回复。")
                            triggered = True
                            break
                
                if triggered:
                    # Pass contact_name for per-contact prompts
                    self.process_and_reply(contact_name, last_message_text)
                    return True
                else:
                    self.logger.info(f"消息不包含任何触发关键词，跳过回复。")
                    return False

            else:
                self.logger.warning(f"在聊天 '{contact_name}' 中未能获取到最后接收的消息。")
                return False # Not processed

        except StaleElementReferenceException:
            self.logger.warning(f"处理 '{contact_name}' 时元素引用失效，将在下次循环重试。")
            return False
        except NoSuchElementException as e:
            # More specific logging about which element wasn't found
            self.logger.warning(f"处理 '{contact_name}' 时未找到预期元素 (检查选择器: {self.contact_name_in_list_selector}?): {e}")
            return False
        except Exception as e:
            self.logger.error(f"处理聊天项 '{contact_name}' 时发生意外错误: {str(e)}")
            return False
    
    def get_last_received_message(self, contact_name):
        """获取当前打开聊天窗口中最后一条*接收*到的消息内容"""
        try:
            # Wait briefly for messages to potentially load
            WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, self.last_message_selector))
            )
            messages = self.driver.find_elements(By.CSS_SELECTOR, self.last_message_selector)
            if messages:
                # Iterate backwards to find the last message NOT sent by us
                for i in range(len(messages) - 1, -1, -1):
                    last_msg = messages[i]
                    msg_class = last_msg.get_attribute('class')
                    
                    # 检查背景颜色，自己的消息通常是绿色背景
                    msg_style = last_msg.get_attribute('style')
                    background_color = ""
                    try:
                        # 尝试获取元素的背景颜色
                        background_color = last_msg.value_of_css_property('background-color')
                        self.logger.debug(f"消息背景颜色: {background_color}, 类名: {msg_class}")
                    except Exception:
                        pass
                        
                    # 通过类名和背景颜色双重判断是否为自己发送的消息
                    # 自己发送的消息通常有"message-send"类或绿色背景
                    is_sent_by_me = ('message-send' in msg_class or 
                                     'message-sys' in msg_class or 
                                     'rgb(169, 236, 155)' in background_color or
                                     'rgb(160, 221, 148)' in background_color or
                                     'rgb(154, 216, 141)' in background_color)
                    
                    self.logger.debug(f"是否为自己发送的消息: {is_sent_by_me}")
                    
                    if not is_sent_by_me:
                        try:
                            # Use the more specific selector for content
                            content_element = last_msg.find_element(By.CSS_SELECTOR, self.received_message_content_selector)
                            return content_element.text.strip()
                        except NoSuchElementException:
                             self.logger.warning(f"在来自 '{contact_name}' 的最后一条消息中未找到内容元素 '{self.received_message_content_selector}'")
                             return None # Content element not found within the message element
                
                self.logger.info(f"在聊天 '{contact_name}' 中未找到接收到的消息。")
                return None # No received messages found
            else:
                 self.logger.info(f"在聊天 '{contact_name}' 中未找到任何消息元素 ({self.last_message_selector}).")
                 return None
        except TimeoutException:
            self.logger.warning(f"等待聊天 '{contact_name}' 的消息元素 ({self.last_message_selector}) 时超时。")
            return None
        except StaleElementReferenceException:
             self.logger.warning(f"获取 '{contact_name}' 的消息时元素已过时。")
             return None
        except Exception as e:
            self.logger.error(f"获取 '{contact_name}' 最后一条消息时出错: {str(e)}")
            return None
    
    def process_and_reply(self, contact_name, message):
        """处理消息并发送回复 (模拟输入, 处理换行)"""
        reply = None
        try:
            self.logger.info(f"为来自 '{contact_name}' 的消息生成回复: {message[:30]}...")
            # Pass contact_name to generate_reply for potential per-contact prompts
            reply = self.ai_model.generate_reply(message, contact_name)

            if not reply or not isinstance(reply, str) or not reply.strip():
                self.logger.error(f"AI模型未能生成有效回复 (回复: {reply})")
                return

            self.logger.log_chat(message, reply)

            try:
                input_box = self.driver.find_element(By.CSS_SELECTOR, self.input_box_selector)
                input_box.clear() # Clear input box first
                
                # Split reply by newline and send line by line with Cmd+Enter
                lines = reply.split('\n')
                num_lines = len(lines)
                
                for i, line in enumerate(lines):
                    input_box.send_keys(line)
                    if i < num_lines - 1: # If not the last line
                        # Send Cmd+Enter for newline (macOS)
                        # Use Keys.CONTROL for Windows/Linux if needed
                        self.logger.debug("Sending Cmd+Enter for newline")
                        input_box.send_keys(Keys.COMMAND, Keys.ENTER)
                        time.sleep(0.1) # Small pause between lines
                
                # Send the final Enter to send the message
                time.sleep(0.5) # Pause before final Enter
                input_box.send_keys(Keys.ENTER)
                self.logger.info(f"已向 '{contact_name}' 发送回复 (处理换行后通过 Enter): {reply[:30]}...")
                time.sleep(1)
            except NoSuchElementException:
                 self.logger.error(f"发送回复时未找到输入框 ({self.input_box_selector})")
            except Exception as send_err:
                 self.logger.error(f"使用输入框发送回复给 '{contact_name}' 时出错: {send_err}")

        except Exception as e:
            self.logger.error(f"回复流程 ('{contact_name}') 中出错: {str(e)}")
    
    def close(self):
        """关闭浏览器驱动"""
        if self.driver:
            self.logger.info("关闭浏览器驱动...")
            try:
                self.driver.quit()
                self.logger.info("浏览器驱动已关闭。")
            except Exception as e:
                 self.logger.error(f"关闭浏览器驱动时出错: {str(e)}")
            finally:
                self.driver = None

    def detect_if_group_chat(self, chat_item_element, contact_name):
         """Attempts to detect if a chat item represents a group chat.
            Uses a guessed selector - VERIFY WITH DEVTOOLS.
         """
         # --- Guessed Implementation (Needs Verification) ---
         # Try to find a common group icon element within the chat list item.
         # The actual class name needs verification using DevTools.
         guessed_group_icon_selector = 'i.web_wechat_icon_groupchat' 
         try:
             # Use find_elements (plural) to avoid NoSuchElementException if not found
             group_icons = chat_item_element.find_elements(By.CSS_SELECTOR, guessed_group_icon_selector)
             if group_icons: # If the list is not empty, we found the icon
                 self.logger.info(f"Chat '{contact_name}' detected as GROUP (found icon: {guessed_group_icon_selector})")
                 return True
             else:
                 # self.logger.debug(f"Chat '{contact_name}' likely NOT a group (icon not found: {guessed_group_icon_selector})")
                 return False
         except Exception as e:
            # Log error during detection but assume not a group
            self.logger.error(f"Error detecting group chat for '{contact_name}' using selector '{guessed_group_icon_selector}': {e}")
            return False
         # --- End Guessed Implementation ---
