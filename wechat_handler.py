from playwright.sync_api import sync_playwright, Page, expect
import time

# Handles interactions with WeChat Web via Playwright

class WeChatHandler:
    def __init__(self, headless=False):
        print("Initializing Playwright...")
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=headless)
        self.page = self.browser.new_page()
        print("Playwright initialized.")

    def login(self):
        print("Navigating to WeChat login page...")
        try:
            # Use web.wechat.com as wx.qq.com might be outdated/restricted
            self.page.goto("https://web.wechat.com/", timeout=60000) 
            print("Login page loaded. Please scan the QR code using your phone.")

            # --- Wait for login success ---
            # Option 1: Wait for a specific element unique to the logged-in state.
            # Inspect the WeChat web interface after login to find a reliable selector.
            # Example (might need adjustment): Wait for the main chat list container
            # login_success_selector = "#app .main" # Example selector, needs verification
            # print(f"Waiting for login success element: {login_success_selector}")
            # self.page.wait_for_selector(login_success_selector, timeout=120000) # Wait up to 120 seconds

            # Option 2 (Simpler but less reliable): Wait for URL change or a long fixed time
            # Wait for URL to change away from the initial login page (might not always happen)
            # Or simply wait for a generous amount of time for the user to scan
            print("Waiting for user to scan QR code (e.g., 60 seconds)...")
            time.sleep(60) # Wait 60 seconds for manual scan

            # Check if login seems successful (e.g., QR code element disappears)
            # This is a basic check, a more robust check is waiting for a post-login element
            qr_code_selector = 'img[mm-src-load="qrcodeLoad"]' # Selector for the QR code image
            if self.page.query_selector(qr_code_selector):
                 print("Login timeout or failed (QR code still visible). Please restart.")
                 # Optionally raise an exception or handle retry logic
                 # raise TimeoutError("Login timed out.")
                 return False
            else:
                print("Login successful (QR code disappeared).")
                return True


        except Exception as e:
            print(f"An error occurred during login: {e}")
            self.close()
            return False


    def listen_for_messages(self, callback):
        """
        Continuously monitors the WeChat chat list for new messages and triggers the callback.
        REQUIRES USER TO VERIFY/UPDATE CSS SELECTORS using browser DevTools.
        """
        print("Starting message listener...")
        # --- Selectors (NEEDS VERIFICATION / UPDATE using DevTools!) ---
        chat_list_selector = "#J_NavChatScrollBody" # Container for chat items - VERIFY!
        chat_item_selector = f"{chat_list_selector} .chat_item" # Individual chat item - VERIFY!
        # Common selectors for unread dots/counts - VERIFY/CHOOSE THE CORRECT ONE(s)!
        unread_selectors = [
            f"{chat_item_selector}:has(span.web_wechat_reddot_middle)", # Small red dot - VERIFY!
            # f"{chat_item_selector}:has(span.icon.web_wechat_reddot_middle)", # Alternative red dot - VERIFY!
            # f"{chat_item_selector}:has(span.unread_count)", # Badge with a number - VERIFY!
        ]
        contact_name_selector = ".nickname .nickname_text" # Selector for contact name within chat_item - VERIFY!
        # Selector for the currently active chat's message area - VERIFY!
        active_chat_messages_selector = "#J_ChatHistory .message" # Selector for individual messages in the active chat - VERIFY!
        # Selector for the text content within a message (relative to message element) - VERIFY!
        message_content_selector = ".content span" # Often wrapped in spans, check structure - VERIFY!

        processed_message_signatures = set() # Keep track of processed messages to avoid duplicates

        try:
            while True: # Loop indefinitely to check for messages
                print(f"Checking for unread messages... (Processed this session: {len(processed_message_signatures)})")
                found_unread_element = None

                # Iterate through potential unread selectors/patterns
                for unread_pattern in unread_selectors:
                    # Find *all* elements matching the unread pattern
                    unread_elements = self.page.query_selector_all(unread_pattern)
                    if unread_elements:
                        print(f"Found {len(unread_elements)} unread indicators using pattern: '{unread_pattern}'")
                        # Prioritize the first one found for processing in this cycle
                        found_unread_element = unread_elements[0]
                        break # Stop checking patterns once one match is found

                if not found_unread_element:
                    # print("No unread messages found.")
                    time.sleep(5) # Wait before checking again
                    continue

                # Process the found unread chat item
                chat_item = found_unread_element # The element itself is the chat_item based on the :has() selector

                try:
                    contact_name_element = chat_item.query_selector(contact_name_selector)
                    if not contact_name_element:
                         print(f"WARNING: Could not find contact name element using '{contact_name_selector}' within the unread item. Skipping.")
                         # Maybe mark this somehow to avoid getting stuck? For now, just wait.
                         time.sleep(5)
                         continue

                    contact_name = contact_name_element.inner_text().strip()
                    print(f"Unread message detected from: {contact_name}")

                    # --- Get Last Message ---
                    # Click the chat item to make it active and potentially mark as read
                    chat_item.click()
                    print(f"Clicked on chat: {contact_name}")
                    # Increased sleep time slightly to allow UI updates and message loading
                    time.sleep(2)

                    # Wait for messages container to be present
                    try:
                         self.page.wait_for_selector(active_chat_messages_selector.split(' ')[0], state="attached", timeout=10000) # Wait for parent container
                    except Exception as wait_error:
                         print(f"WARNING: Timed out waiting for message container '{active_chat_messages_selector.split(' ')[0]}' for {contact_name}. Error: {wait_error}. Skipping.")
                         time.sleep(5)
                         continue


                    # Get *all* message elements in the active chat
                    message_elements = self.page.query_selector_all(active_chat_messages_selector)
                    if not message_elements:
                        print(f"WARNING: Could not find any message elements using '{active_chat_messages_selector}' for {contact_name} after clicking. Skipping.")
                        time.sleep(5)
                        continue

                    # Assume the last message is the newest one
                    last_message_element = message_elements[-1]
                    message_content_element = last_message_element.query_selector(message_content_selector)

                    if not message_content_element:
                        print(f"WARNING: Could not extract message content using '{message_content_selector}' from the last message for {contact_name}. Skipping.")
                        time.sleep(5)
                        continue

                    message_content = message_content_element.inner_text().strip()

                    # --- Avoid Duplicate Processing ---
                    # Create a unique signature for the message (sender + content)
                    # Consider adding a timestamp or message ID if available for better uniqueness
                    message_signature = f"{contact_name}::{message_content}"
                    if message_signature in processed_message_signatures:
                        print(f"Message already processed: {message_signature}. Skipping.")
                        # Add a small delay even if skipping duplicates
                        time.sleep(1)
                        continue # Skip if already processed

                    print(f"Extracted new message: '{message_content}' from {contact_name}")
                    processed_message_signatures.add(message_signature) # Mark as processed

                    # --- Execute Callback ---
                    callback(contact_name, message_content) # Pass data to the main logic

                    # Optional: Clear older signatures periodically if memory becomes an issue
                    if len(processed_message_signatures) > 500: # Limit cache size
                         print("Clearing old message signatures...")
                         processed_message_signatures.clear()

                except Exception as e:
                    # Catch errors during processing of a single chat item
                    print(f"ERROR processing chat item for '{contact_name if 'contact_name' in locals() else 'Unknown'}': {e}")
                    # Add a delay to avoid potentially hammering a broken state
                    time.sleep(10)

                # Wait a bit before checking the whole list again, even after processing one
                print("Waiting before next check...")
                time.sleep(5) # Wait 5 seconds

        except KeyboardInterrupt:
            print("Message listener stopped by user.")
        except Exception as e:
            # Catch errors in the main loop (e.g., page closed unexpectedly)
            print(f"FATAL ERROR in message listener loop: {e}")
        finally:
            print("Message listener finished.")


    def send_message(self, contact_name, message):
        print(f"Sending message to {contact_name}: {message} (Not implemented yet)")
        pass

    def close(self):
        print("Closing browser...")
        if hasattr(self, 'browser') and self.browser:
            self.browser.close()
        if hasattr(self, 'playwright') and self.playwright:
            self.playwright.stop()
        print("Browser closed.")
