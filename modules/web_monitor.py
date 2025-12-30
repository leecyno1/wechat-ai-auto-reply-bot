from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    NoAlertPresentException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    UnexpectedAlertPresentException,
)
import time
import os # Import os module
from pathlib import Path
import stat
import threading
import re
from contextlib import contextmanager

class WebMonitor:
    def __init__(self, logger, ai_model, config, message_callback=None):
        self.logger = logger
        self.ai_model = ai_model
        self.config = config # This should be the web_monitor section of the config
        self.message_callback = message_callback
        self.driver = None
        self.is_running = False
        # Serialize all Selenium operations (monitor loop vs. sending replies) to avoid UI switching races.
        self._driver_lock = threading.RLock()
        # Give outgoing sends priority: pause monitoring while sending to reduce reply latency.
        self._pause_event = threading.Event()
        self._pause_lock = threading.RLock()
        self._pause_count = 0
        
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

    @contextmanager
    def _pause_monitoring(self):
        with self._pause_lock:
            self._pause_count += 1
            self._pause_event.set()
        try:
            yield
        finally:
            with self._pause_lock:
                self._pause_count -= 1
                if self._pause_count <= 0:
                    self._pause_count = 0
                    self._pause_event.clear()

    def start(self):
        """启动微信Web监控"""
        if self.is_running:
            self.logger.warning("WebMonitor already running")
            return True
        
        success = self.initialize()
        if success:
            self.is_running = True
        return success

    def stop(self):
        """停止微信Web监控"""
        self.is_running = False
        self.close()

    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        try:
            if not self.driver:
                return False
            
            # 检查登录成功元素是否存在
            login_elements = self.driver.find_elements(By.CSS_SELECTOR, self.login_success_selector)
            return len(login_elements) > 0
            
        except Exception as e:
            self.logger.error(f"检查登录状态失败: {e}")
            return False

    def is_qr_code_visible(self) -> bool:
        """检查二维码是否可见"""
        try:
            if not self.driver:
                return False
            
            # 检查二维码元素
            qr_selectors = [
                '.qrcode',
                '.login_box_qr',
                '[data-role="qrcode"]',
                '.js_qr_code_default_login'
            ]
            
            for selector in qr_selectors:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements and elements[0].is_displayed():
                        return True
                except:
                    continue
            
            return False
            
        except Exception as e:
            self.logger.error(f"检查二维码状态失败: {e}")
            return False

    def get_current_user_name(self) -> str:
        """获取当前用户名"""
        try:
            if not self.driver:
                return "未知用户"
            
            # 尝试不同的用户名选择器
            selectors = [
                '.nickname .nickname_text',
                '.user_info .nickname',
                '.header .nickname',
                '.account .nickname'
            ]
            
            for selector in selectors:
                try:
                    element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if element and element.text:
                        return element.text
                except:
                    continue
            
            return "微信用户"
            
        except Exception as e:
            self.logger.error(f"获取用户名失败: {e}")
            return "未知用户"

    def check_new_messages(self):
        """检查新消息"""
        try:
            if not self.is_logged_in():
                return
            
            # 查找未读消息
            unread_chats = self.driver.find_elements(By.CSS_SELECTOR, self.unread_msg_selector)
            
            for chat in unread_chats:
                try:
                    # 点击聊天项
                    chat.click()
                    time.sleep(1)
                    
                    # 获取联系人名称
                    contact_name = self._get_active_contact_name()
                    if not contact_name:
                        continue
                    
                    # 检查是否在过滤列表中
                    if not self._should_process_contact(contact_name):
                        continue
                    
                    # 获取最新消息
                    latest_message = self._get_latest_message()
                    if latest_message:
                        message_data = {
                            "sender": contact_name,
                            "content": latest_message,
                            "timestamp": time.time(),
                            "is_group": self._is_group_chat()
                        }
                        
                        # 检查是否已处理过
                        signature = f"{contact_name}:{latest_message}:{message_data['timestamp']:.0f}"
                        if signature not in self.processed_message_signatures:
                            self.processed_message_signatures.add(signature)
                            
                            # 调用消息回调
                            if self.message_callback:
                                self.message_callback(message_data)
                            
                            # 处理消息（自动回复等）
                            self.process_and_reply(contact_name, latest_message, message_data)
                
                except Exception as e:
                    self.logger.error(f"处理聊天失败: {e}")
                    continue
            
        except Exception as e:
            self.logger.error(f"检查新消息失败: {e}")

    def _get_active_contact_name(self) -> str:
        """获取当前活跃聊天的联系人名称"""
        try:
            # 尝试不同的选择器
            selectors = [
                '.chat_hd .nickname',
                '.chat_info .nickname',
                '.chat_title .nickname',
                '.header .chat_name'
            ]
            
            for selector in selectors:
                try:
                    element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    if element and element.text:
                        return element.text.strip()
                except:
                    continue
            
            return ""
            
        except Exception as e:
            self.logger.error(f"获取联系人名称失败: {e}")
            return ""

    def _get_latest_message(self) -> str:
        """获取最新消息内容"""
        try:
            # 获取所有消息元素
            messages = self.driver.find_elements(By.CSS_SELECTOR, self.last_message_selector)
            
            if not messages:
                return ""
            
            # 获取最后一条消息
            last_message = messages[-1]
            
            # 尝试获取消息内容
            try:
                content_element = last_message.find_element(By.CSS_SELECTOR, self.received_message_content_selector)
                return content_element.text.strip()
            except:
                # 如果找不到内容元素，直接返回消息文本
                return last_message.text.strip()
            
        except Exception as e:
            self.logger.error(f"获取最新消息失败: {e}")
            return ""

    def _is_group_chat(self) -> bool:
        """判断是否为群聊"""
        try:
            # 尝试通过页面元素判断是否为群聊
            group_indicators = [
                '.chat_hd .chat_members',
                '.group_chat_indicator',
                '[data-chattype="group"]'
            ]
            
            for selector in group_indicators:
                try:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        return True
                except:
                    continue
            
            # 通过联系人名称判断（群聊通常有特定格式）
            contact_name = self._get_active_contact_name()
            if contact_name and ('群' in contact_name or len(contact_name) > 10):
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"判断群聊失败: {e}")
            return False

    def send_message(self, contact: str, message: str) -> bool:
        """发送消息到指定联系人"""
        try:
            if not self.is_logged_in():
                self.logger.error("未登录，无法发送消息")
                return False
            
            # 发送过程中不要被监控线程切走窗口
            with self._pause_monitoring():
                with self._driver_lock:
                    self._dismiss_any_alert(context="send_message")
                    # 查找并点击联系人
                    if not self._select_contact(contact):
                        self.logger.error(f"找不到联系人: {contact}")
                        return False
                    
                    # 查找输入框
                    try:
                        input_box = WebDriverWait(self.driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, self.input_box_selector))
                        )
                    except TimeoutException:
                        self.logger.error("找不到输入框")
                        return False
                    
                    # 发送消息
                    input_box.clear()
                    # 处理换行，避免消息未完整输入或被拆分发送
                    lines = str(message).split('\n')
                    for i, line in enumerate(lines):
                        input_box.send_keys(line)
                        if i < len(lines) - 1:
                            input_box.send_keys(Keys.COMMAND, Keys.ENTER)
                            time.sleep(0.02)
                    input_box.send_keys(Keys.ENTER)
            
            self.logger.info(f"消息发送成功: {contact} -> {message[:50]}...")
            return True
            
        except Exception as e:
            self.logger.error(f"发送消息失败: {e}")
            return False

    def send_message_with_ack(self, contact: str, message: str, ack_timeout_sec: float = 3.0) -> bool:
        """
        发送消息并等待“发送回执”(ACK)：
        - 在 DOM 中观察“我方最后一条消息”是否出现/更新为本次发送内容
        - 主要用于提升稳定性：防止 UI 卡顿/焦点丢失导致“看似发送但未发送”
        """
        if ack_timeout_sec <= 0:
            return self.send_message(contact, message)

        try:
            if not self.is_logged_in():
                self.logger.error("未登录，无法发送消息(ack)")
                return False

            with self._pause_monitoring():
                with self._driver_lock:
                    self._dismiss_any_alert(context="send_message_with_ack")
                    before_sig = self._get_last_outgoing_signature()
                    ok = self.send_message(contact, message)
                    if not ok:
                        return False
                    if self._wait_for_outgoing_ack(message, before_sig=before_sig, timeout_sec=ack_timeout_sec):
                        return True
                    self.logger.warning(
                        "发送 ACK 超时: contact=%s timeout=%.1fs",
                        contact,
                        float(ack_timeout_sec),
                    )
                    # ACK is best-effort; avoid duplicate retries due to DOM/selector uncertainty.
                    return True
        except Exception as e:
            self.logger.error(f"发送消息(ack)失败: {e}")
            return False

    def _normalize_text_for_ack(self, text: str) -> str:
        t = "" if text is None else str(text)
        t = t.replace("\r\n", "\n").replace("\r", "\n")
        t = t.replace("\u200b", "").replace("\ufeff", "")
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _extract_message_text(self, message_el) -> str:
        try:
            try:
                content_element = message_el.find_element(By.CSS_SELECTOR, self.received_message_content_selector)
                return (content_element.text or "").strip()
            except Exception:
                return (message_el.text or "").strip()
        except Exception:
            return ""

    def _is_outgoing_message_el(self, message_el) -> bool:
        try:
            cls = (message_el.get_attribute("class") or "").lower()
            # common patterns: "message me", "message ng-scope me"
            return (" me" in f" {cls} ") or ("from_me" in cls) or ("self" in cls)
        except Exception:
            return False

    def _get_last_outgoing_signature(self) -> tuple[int, str]:
        """
        Returns a best-effort signature (message_count, last_outgoing_text).
        Falls back to last message overall if outgoing cannot be determined.
        """
        try:
            messages = self.driver.find_elements(By.CSS_SELECTOR, self.last_message_selector)
            total = len(messages)
            # Prefer a message element that looks like "sent by me"
            for el in reversed(messages):
                if self._is_outgoing_message_el(el):
                    return (total, self._extract_message_text(el))
            # Fallback: last message overall
            for el in reversed(messages):
                txt = self._extract_message_text(el)
                if txt:
                    return (total, txt)
            return (total, "")
        except Exception:
            return (0, "")

    def _wait_for_outgoing_ack(self, expected_text: str, before_sig: tuple[int, str], timeout_sec: float) -> bool:
        expected_norm = self._normalize_text_for_ack(expected_text)
        if not expected_norm:
            # Empty messages are not supported; treat as failed.
            return False

        deadline = time.time() + float(timeout_sec)
        last_seen_sig: tuple[int, str] = before_sig
        while time.time() < deadline:
            try:
                after_sig = self._get_last_outgoing_signature()
                # Ensure either message count advanced or last text changed (avoid matching an older identical message)
                changed = after_sig != before_sig and after_sig != last_seen_sig
                after_norm = self._normalize_text_for_ack(after_sig[1])
                if changed and expected_norm in after_norm:
                    return True
                last_seen_sig = after_sig
            except StaleElementReferenceException:
                pass
            except Exception:
                pass
            time.sleep(0.12)

        return False

    def _select_contact(self, contact_name: str) -> bool:
        """选择联系人"""
        try:
            # 防止与监控线程同时操作 DOM
            with self._driver_lock:
                self._dismiss_any_alert(context="_select_contact")
                # 优先在左侧会话列表(chat_item)里精准定位，避免误点聊天内容区的同名文本
                xpaths = [
                    # exact match
                    (
                        "//*[contains(@class,'chat_item')]"
                        "//*[contains(@class,'nickname_text') and normalize-space(text())=$name]"
                        "/ancestor::*[contains(@class,'chat_item')][1]"
                    ),
                ]

                # Selenium does not support xpath variables; we do minimal escaping for quotes.
                safe_name = str(contact_name).replace('"', '\\"')
                try:
                    # Reduce implicit wait during bulk DOM scans to avoid long stalls.
                    try:
                        self.driver.implicitly_wait(0)
                    except Exception:
                        pass

                    def _try_click_by_xpaths() -> bool:
                        for xp in xpaths:
                            try:
                                resolved = xp.replace("$name", f'"{safe_name}"')
                                items = self.driver.find_elements(By.XPATH, resolved)
                                for item in items[:5]:
                                    try:
                                        self.driver.execute_script(
                                            "arguments[0].scrollIntoView({block: 'center'});", item
                                        )
                                    except Exception:
                                        pass
                                    try:
                                        item.click()
                                    except Exception:
                                        continue

                                    # Verify the active chat header matches, to avoid sending to a wrong chat
                                    try:
                                        WebDriverWait(self.driver, 2).until(
                                            lambda d: bool(self._get_active_contact_name())
                                        )
                                    except Exception:
                                        pass
                                    active = (self._get_active_contact_name() or "").strip()
                                    requested = str(contact_name or "").strip()
                                    if active and requested:
                                        if active == requested:
                                            return True
                                        # If the UI decorates the title, allow tight containment.
                                        if requested in active or active in requested:
                                            return True
                                        self.logger.warning(
                                            "选中聊天不匹配: requested='%s' active='%s' (继续查找)",
                                            requested,
                                            active,
                                        )
                                        continue
                                    return True
                            except Exception:
                                continue
                        return False

                    # 1) Try exact match directly from visible chat list
                    if _try_click_by_xpaths():
                        return True

                    # 2) Filter via search box, then retry exact match (much faster for large lists)
                    if self._filter_chat_list_for_contact(str(contact_name or "")):
                        if _try_click_by_xpaths():
                            self._clear_chat_search_box()
                            return True
                        self._clear_chat_search_box()

                    # 3) Final fallback (less strict): contains match, but still limited and verified
                    fallback_xpaths = [
                        (
                            "//*[contains(@class,'chat_item')]"
                            "//*[contains(@class,'nickname_text') and contains(normalize-space(text()),$name)]"
                            "/ancestor::*[contains(@class,'chat_item')][1]"
                        ),
                    ]
                    for xp in fallback_xpaths:
                        try:
                            resolved = xp.replace("$name", f'"{safe_name}"')
                            items = self.driver.find_elements(By.XPATH, resolved)
                            for item in items:
                                try:
                                    self.driver.execute_script(
                                        "arguments[0].scrollIntoView({block: 'center'});", item
                                    )
                                except Exception:
                                    pass
                                try:
                                    item.click()
                                    active = (self._get_active_contact_name() or "").strip()
                                    requested = str(contact_name or "").strip()
                                    if active and requested and (requested in active or active in requested):
                                        return True
                                except Exception:
                                    continue
                        except Exception:
                            continue

                    return False
                finally:
                    # Restore default implicit wait for other operations
                    try:
                        self.driver.implicitly_wait(5)
                    except Exception:
                        pass
            
        except Exception as e:
            self.logger.error(f"选择联系人失败: {e}")
            return False

    def _filter_chat_list_for_contact(self, contact_name: str) -> bool:
        name = str(contact_name or "").strip()
        if not name:
            return False
        selectors = self.config.get(
            "search_box_selectors",
            [
                "#search_bar input",
                ".search_bar input",
                ".frm_search",
                "input[placeholder*='搜索']",
                "input[placeholder*='Search']",
            ],
        )
        for sel in selectors:
            try:
                box = self.driver.find_element(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            try:
                box.click()
            except Exception:
                pass
            try:
                box.send_keys(Keys.COMMAND, "a")
                box.send_keys(Keys.BACKSPACE)
            except Exception:
                try:
                    box.clear()
                except Exception:
                    pass
            try:
                box.send_keys(name)
                time.sleep(0.15)
                return True
            except Exception:
                continue
        return False

    def _clear_chat_search_box(self) -> None:
        selectors = self.config.get(
            "search_box_selectors",
            [
                "#search_bar input",
                ".search_bar input",
                ".frm_search",
                "input[placeholder*='搜索']",
                "input[placeholder*='Search']",
            ],
        )
        for sel in selectors:
            try:
                box = self.driver.find_element(By.CSS_SELECTOR, sel)
            except Exception:
                continue
            try:
                box.click()
            except Exception:
                pass
            try:
                box.send_keys(Keys.COMMAND, "a")
                box.send_keys(Keys.BACKSPACE)
                box.send_keys(Keys.ESCAPE)
                return
            except Exception:
                try:
                    box.clear()
                    return
                except Exception:
                    continue

    def get_contact_list(self):
        """获取联系人列表"""
        try:
            if not self.is_logged_in():
                return []
            
            contacts = []
            contact_elements = self.driver.find_elements(By.CSS_SELECTOR, '.chat_item .nickname_text')
            
            for element in contact_elements:
                if element.text:
                    contacts.append({
                        "name": element.text.strip(),
                        "type": "contact"
                    })
            
            return contacts
            
        except Exception as e:
            self.logger.error(f"获取联系人列表失败: {e}")
            return []

    def quit(self):
        """退出WebMonitor"""
        self.stop()

    def close(self):
        """关闭浏览器"""
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
                self.logger.info("浏览器已关闭")
        except Exception as e:
            self.logger.error(f"关闭浏览器失败: {e}")

    def _should_process_contact(self, contact_name: str) -> bool:
        """检查是否应该处理该联系人的消息"""
        if self.contact_list_mode == 'whitelist':
            return contact_name in self.contact_whitelist
        else:  # blacklist mode
            return contact_name not in self.contact_blacklist

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

            driver_path = ChromeDriverManager().install()
            try:
                p = Path(driver_path)
                # webdriver-manager may (incorrectly) return a non-binary companion file on some platforms
                # e.g. THIRD_PARTY_NOTICES.chromedriver, which will raise "Exec format error".
                candidate_names = ("chromedriver", "chromedriver.exe")
                if p.name not in candidate_names:
                    for name in candidate_names:
                        candidate = p.parent / name
                        if candidate.exists():
                            driver_path = str(candidate)
                            break

                # Ensure the resolved driver is executable (some caches unpack without +x on macOS)
                try:
                    if os.path.exists(driver_path) and not os.access(driver_path, os.X_OK):
                        st_mode = os.stat(driver_path).st_mode
                        os.chmod(
                            driver_path,
                            st_mode
                            | stat.S_IXUSR
                            | stat.S_IXGRP
                            | stat.S_IXOTH,
                        )
                except Exception:
                    # best-effort; Selenium will raise if still not executable
                    pass
            except Exception:
                # best-effort fallback; keep the original driver_path
                pass

            service = ChromeService(driver_path)
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
        driver_lock_timeout = float(self.config.get("driver_lock_timeout_sec", 0.25))
        active_chat_check_enabled = bool(self.config.get("active_chat_check_enabled", True))
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
                
                # Ensure any unexpected dialogs won't block further DOM operations
                self._dismiss_any_alert(context="monitor_messages")

                # If a send is in progress, back off to reduce reply latency / wrong-chat risks.
                if self._pause_event.is_set():
                    time.sleep(0.05)
                    continue
                
                # 避免在“发送回复”期间切换聊天，导致漏发/错发：监控与发送共享同一把锁
                # Keep the lock timeout short so sending replies is not delayed by monitoring.
                if not self._driver_lock.acquire(timeout=driver_lock_timeout):
                    time.sleep(0.05)
                    continue

                try:
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

                    # --- 2. 如果没有红点项被处理，检查活跃聊天窗口 --- 
                    if active_chat_check_enabled and not processed_in_cycle:
                        try:
                            active_chat_element = self.driver.find_element(By.CSS_SELECTOR, self.active_chat_selector)
                            self.logger.debug(f"检查活跃聊天窗口 (选择器: {self.active_chat_selector})")
                            if self.process_chat_item(active_chat_element, check_only_new=True): # Pass flag to only check new
                                processed_in_cycle = True
                        except NoSuchElementException:
                            self.logger.debug("当前无活跃聊天窗口或选择器无效。")
                        except Exception as active_err:
                            self.logger.error(f"检查活跃聊天 ({self.active_chat_selector}) 时出错: {active_err}")
                finally:
                    self._driver_lock.release()

                # --- 3. 等待下次检查 ---
                # self.logger.debug("完成检查周期，等待...")
                if processed_in_cycle:
                    # Quick follow-up to reduce perceived latency when messages are arriving.
                    time.sleep(0.2)
                else:
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
        except UnexpectedAlertPresentException:
            # Some WeChat web flows trigger blocking dialogs (e.g., plugin prompts).
            self._dismiss_any_alert(context="is_browser_alive")
            return True
        except Exception as e:
            self.logger.warning(f"检查浏览器状态时出错 (可能已关闭): {e}")
            return False

    def _dismiss_any_alert(self, context: str = "") -> bool:
        """
        Best-effort handler for unexpected JS dialogs that block WebDriver.
        Prefer dismiss to avoid triggering installs/side-effects.
        """
        if not self.driver:
            return False
        try:
            alert = self.driver.switch_to.alert
            try:
                text = alert.text
            except Exception:
                text = ""

            action = "none"
            try:
                alert.dismiss()
                action = "dismiss"
            except Exception:
                try:
                    alert.accept()
                    action = "accept"
                except Exception:
                    action = "none"

            self.logger.warning(
                "Detected and handled alert (%s): action=%s text=%s",
                context or "unknown",
                action,
                (text or "")[:200],
            )
            return action != "none"
        except NoAlertPresentException:
            return False
        except Exception as e:
            self.logger.warning(f"处理弹窗失败({context}): {e}")
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
            if self._pause_event.is_set():
                return False
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
                    if self._pause_event.is_set():
                        return False
                    chat_item_element.click()
                    # Wait for chat to load (avoid fixed sleep)
                    chat_load_timeout = float(self.config.get("chat_load_timeout_sec", 2.0))
                    try:
                        if self._pause_event.is_set():
                            return False
                        WebDriverWait(self.driver, chat_load_timeout).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, self.last_message_selector))
                        )
                    except Exception:
                        if self._pause_event.is_set():
                            return False
                        WebDriverWait(self.driver, chat_load_timeout).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, self.input_box_selector))
                        )
                 except Exception as click_err:
                     self.logger.error(f"点击聊天项 '{contact_name}' 时出错: {click_err}")
                     return False # Could not process

            # 获取最后一条接收到的消息
            # Active-chat polling should be fast to avoid blocking outgoing sends.
            last_message_text = self.get_last_received_message(contact_name, fast=bool(check_only_new))

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
                    if not self._is_bot_mentioned_in_text(last_message_text):
                        self.logger.info(f"群聊消息未 @{self.bot_group_nickname}，跳过回复。")
                        # 记录消息但不记录未回复原因
                        if hasattr(self.logger, "log_chat"):
                            self.logger.log_chat(last_message_text, "")
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
                    reply = self.process_and_reply(contact_name, last_message_text)
                    # 记录带有实际回复的消息
                    if reply and hasattr(self.logger, "log_chat"):
                        self.logger.log_chat(last_message_text, reply)
                    return True
                else:
                    self.logger.info(f"消息不包含任何触发关键词，跳过回复。")
                    # 记录消息但不记录未回复原因
                    if hasattr(self.logger, "log_chat"):
                        self.logger.log_chat(last_message_text, "")
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
    
    def get_last_received_message(self, contact_name, fast: bool = False):
        """获取当前打开聊天窗口中最后一条*接收*到的消息内容"""
        if fast:
            message_load_timeout = float(self.config.get("message_load_timeout_fast_sec", 0.2))
            max_attempts = int(self.config.get("message_load_fast_attempts", 1))
        else:
            message_load_timeout = float(self.config.get("message_load_timeout_sec", 2.0))
            max_attempts = int(self.config.get("message_load_attempts", 3))

        max_attempts = max(1, max_attempts)
        for attempt in range(max_attempts):
            if self._pause_event.is_set():
                return None
            try:
                # Wait briefly for messages to potentially load.
                # In fast mode, avoid long waits to keep UI free for sending.
                try:
                    WebDriverWait(self.driver, message_load_timeout).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, self.last_message_selector))
                    )
                except TimeoutException:
                    if fast:
                        return None
                    raise
                messages = self.driver.find_elements(By.CSS_SELECTOR, self.last_message_selector)
                if messages:
                    # Iterate backwards to find the last message NOT sent by us
                    for i in range(len(messages) - 1, -1, -1):
                        if self._pause_event.is_set():
                            return None
                        last_msg = messages[i]
                        msg_class = last_msg.get_attribute('class') or ''
                        
                        # 检查背景颜色，自己的消息通常是绿色背景
                        background_color = ""
                        try:
                            background_color = last_msg.value_of_css_property('background-color')
                            self.logger.debug(f"消息背景颜色: {background_color}, 类名: {msg_class}")
                        except Exception:
                            pass
                            
                        # 通过类名和背景颜色双重判断是否为自己发送的消息
                        is_sent_by_me = (
                            'message-send' in msg_class
                            or 'message-sys' in msg_class
                            or 'rgb(169, 236, 155)' in background_color
                            or 'rgb(160, 221, 148)' in background_color
                            or 'rgb(154, 216, 141)' in background_color
                        )
                        
                        self.logger.debug(f"是否为自己发送的消息: {is_sent_by_me}")
                        
                        if not is_sent_by_me:
                            try:
                                content_element = last_msg.find_element(
                                    By.CSS_SELECTOR, self.received_message_content_selector
                                )
                                return content_element.text.strip()
                            except NoSuchElementException:
                                self.logger.warning(
                                    f"在来自 '{contact_name}' 的最后一条消息中未找到内容元素 "
                                    f"'{self.received_message_content_selector}'，使用fallback文本。"
                                )
                                text = (last_msg.text or "").strip()
                                return text if text else None
                    
                    self.logger.info(f"在聊天 '{contact_name}' 中未找到接收到的消息。")
                    return None
                else:
                    self.logger.info(f"在聊天 '{contact_name}' 中未找到任何消息元素 ({self.last_message_selector}).")
                    return None
            except StaleElementReferenceException:
                if fast:
                    return None
                self.logger.warning(f"获取 '{contact_name}' 的消息时元素已过时，重试 {attempt + 1}/{max_attempts}")
                time.sleep(0.3)
                continue
            except TimeoutException:
                self.logger.warning(f"等待聊天 '{contact_name}' 的消息元素 ({self.last_message_selector}) 时超时。")
                return None
            except Exception as e:
                self.logger.error(f"获取 '{contact_name}' 最后一条消息时出错: {str(e)}")
                return None
        return None
    
    def process_and_reply(self, contact_name, message):
        """处理消息并发送回复 (模拟输入, 处理换行)"""
        reply = None
        try:
            # 无论何种模式，都先输出收到的消息
            self.logger.info(f"📨 收到来自 '{contact_name}' 的消息: {message}")
            
            # 如果有消息回调（Gateway模式），则调用回调而不是直接生成AI回复
            if self.message_callback:
                is_group = False
                try:
                    is_group = self._is_group_chat()
                except Exception:
                    is_group = False
                message_data = {
                    'from': contact_name,
                    'content': message,
                    'timestamp': time.time(),
                    'sender': contact_name,
                    'is_group': is_group,
                }
                self.logger.info(f"🔄 调用消息回调处理来自 '{contact_name}' 的消息")
                callback_reply = self.message_callback(message_data)
                return callback_reply  # Gateway模式通常返回None，不直接回复
            
            # Standalone模式：生成AI回复
            self.logger.info(f"🤖 为来自 '{contact_name}' 的消息生成AI回复...")
            
            # 原有的AI回复逻辑（standalone模式）
            if not self.ai_model:
                self.logger.warning("没有AI模型配置，跳过回复生成")
                return None
                
            # Pass contact_name to generate_reply for potential per-contact prompts
            reply = self.ai_model.generate_reply(message, contact_name)

            if not reply or not isinstance(reply, str) or not reply.strip():
                self.logger.error(f"AI模型未能生成有效回复 (回复: {reply})")
                return None

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
                return reply
            except NoSuchElementException:
                 self.logger.error(f"发送回复时未找到输入框 ({self.input_box_selector})")
                 return None
            except Exception as send_err:
                 self.logger.error(f"使用输入框发送回复给 '{contact_name}' 时出错: {send_err}")
                 return None

        except Exception as e:
            self.logger.error(f"回复流程 ('{contact_name}') 中出错: {str(e)}")
            return None
    
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
         """
         Attempts to detect if the currently opened chat is a group chat.
         Prefer robust checks (header / attributes) over guessed icons to avoid
         accidentally replying to group chats.
         """
         # 1) Attribute-based hint (often present on chat list items)
         try:
             for attr in ("data-username", "data-uid", "username", "id"):
                 v = chat_item_element.get_attribute(attr)
                 if isinstance(v, str) and v.endswith("@chatroom"):
                     return True
         except Exception:
             pass

         # 2) Active-chat DOM indicators (best-effort)
         try:
             return bool(self._is_group_chat())
         except Exception:
             pass

         # 3) Conservative fallback heuristics
         try:
             name = str(contact_name or "").strip()
             if "群" in name:
                 return True
         except Exception:
             pass
         return False

    def _is_bot_mentioned_in_text(self, text: str) -> bool:
        """
        Detect @mention in group messages.
        - Handles both half-width and full-width at sign.
        - Allows optional whitespace after '@'.
        """
        nickname = str(self.bot_group_nickname or "").strip()
        if not nickname:
            return False
        t = "" if text is None else str(text)
        # Common: "@昵称" / "＠昵称" / "@ 昵称"
        pattern = r"[@＠]\s*" + re.escape(nickname)
        try:
            return re.search(pattern, t) is not None
        except Exception:
            return f"@{nickname}" in t or f"＠{nickname}" in t
