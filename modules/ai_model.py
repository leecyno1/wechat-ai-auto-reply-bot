import requests
import json
import time
import os # Import os module

class AIModel:
    def __init__(self, logger, config):
        self.logger = logger
        self.config = config if isinstance(config, dict) else {}
        # Assume only OpenAI compatible API is used now
        self.model_type = self.config.get('model_type', 'openai') 
        if self.model_type != 'openai':
            self.logger.warning(f"Configured model_type '{self.model_type}' is not 'openai'. Assuming OpenAI compatible API.")
            self.model_type = 'openai' # Force to openai compatible mode
            
        # --- Get API Key: Prioritize Environment Variable --- 
        self.api_key = os.environ.get('AI_API_KEY')
        if not self.api_key:
            self.logger.info("AI_API_KEY environment variable not found, trying config file.")
            self.api_key = self.config.get('api_key', '') # Fallback to config
            if not self.api_key:
                 self.logger.warning("API Key not found in environment variable or config file.")
        else:
             self.logger.info("Loaded API Key from AI_API_KEY environment variable.")
        # --- End API Key Loading ---
        
        self.api_url = self.config.get('api_url', '')
        self.headers = self.prepare_headers()
        # Placeholder for conversation history {contact_name: [messages]}
        self.conversation_history = {}
        self.context_length = self.config.get('context_length', 5)
        self.contact_prompts = self.config.get('contact_prompts', {})
        self.default_system_prompt = self.config.get('system_prompt', '你是一个有用的助手')
        self.question_model_name = self.config.get('question_model_name', None)
        self.default_model_name = self.config.get('model_name', None)
        self.question_keywords = self.config.get('question_keywords', [])

        if not self.default_model_name:
            self.logger.error("Configuration error: 'model_name' (default model) is not set in ai_model config.")
            # Potentially raise an error or handle this state

        
    def prepare_headers(self):
        """准备OpenAI兼容API请求的头部信息"""
        if not self.api_key:
            self.logger.warning("API key (api_key) is missing in config.")
        return {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }
    
    def _is_question(self, message):
        """Simple check if the message seems like a question based on keywords."""
        if not self.question_keywords:
            return False
        message_lower = message.lower()
        for keyword in self.question_keywords:
            # Check for keyword presence, potentially at the end for question marks
            if keyword == '?' and message_lower.endswith('?'):
                return True
            elif keyword != '?' and keyword in message_lower:
                 return True
        return False

    def generate_reply(self, message, contact_name=None):
        """生成回复 (仅支持 OpenAI 兼容 API)"""
        self.logger.debug(f"Generating reply for contact: {contact_name}, message: {message[:30]}...")
        try:
            # Determine which model to use
            model_to_use = self.default_model_name
            if self.question_model_name and self._is_question(message):
                model_to_use = self.question_model_name
                self.logger.info(f"Detected question, using model: {model_to_use}")
            else:
                 self.logger.info(f"Using default model: {model_to_use}")

            if not model_to_use:
                 self.logger.error("No appropriate model name found (check default 'model_name' and 'question_model_name' in config).")
                 return "抱歉，模型配置错误，无法回复。"

            # Get context and specific prompt
            system_prompt = self.contact_prompts.get(contact_name, self.default_system_prompt)
            history = self.conversation_history.get(contact_name, [])

            # Prepare message list for API
            messages_for_api = [
                {"role": "system", "content": system_prompt}
            ]
            messages_for_api.extend(history) # Add past messages
            messages_for_api.append({"role": "user", "content": message}) # Add current message

            # Generate reply using the selected model and context
            reply_content = self._call_openai_api(model_to_use, messages_for_api)

            # Update conversation history if reply is successful
            if reply_content:
                # Add user message and assistant reply to history
                if contact_name:
                    current_history = self.conversation_history.get(contact_name, [])
                    current_history.append({"role": "user", "content": message})
                    current_history.append({"role": "assistant", "content": reply_content})
                    # Keep history within context_length (pairs of user/assistant messages)
                    max_history_items = self.context_length * 2
                    if len(current_history) > max_history_items:
                        # Remove the oldest messages (keeping the most recent context_length interactions)
                        current_history = current_history[-max_history_items:]
                    self.conversation_history[contact_name] = current_history
                    self.logger.debug(f"Updated history for {contact_name}. New length: {len(current_history)}")
            
            return reply_content

        except Exception as e:
            self.logger.error(f"生成回复时出错: {str(e)}", exc_info=True)
            return "抱歉，处理回复时遇到内部错误。"
    
    def _call_openai_api(self, model_name, messages):
        """Internal method to call the OpenAI compatible API."""
        if not self.api_key or not self.api_url:
             self.logger.error("API key or URL is missing in config.")
             return "抱歉，API 配置不完整。"

        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": self.config.get('max_tokens', 150),
            "temperature": self.config.get('temperature', 0.7)
            # Add other compatible parameters like top_p if needed
        }
        
        self.logger.debug(f"Calling API. Model: {model_name}, Messages Count: {len(messages)}")
        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                data=json.dumps(payload),
                timeout=60 # Increased timeout slightly
            )
            response.raise_for_status() 
            
            response_data = response.json()
            if 'choices' in response_data and len(response_data['choices']) > 0:
                 reply_content = response_data['choices'][0]['message']['content'].strip()
                 usage = response_data.get('usage', {})
                 self.logger.info(f"API 回复生成成功. Model: {model_name}, Tokens used: {usage.get('total_tokens', 'N/A')}")
                 return reply_content
            else:
                 self.logger.error(f"API 响应格式错误: {response_data}")
                 return "抱歉，从API获取回复时出错 (格式错误)。"
                 
        except requests.exceptions.Timeout:
             self.logger.error(f"API 请求超时 ({payload.get('timeout')}s). Model: {model_name}")
             return "抱歉，连接AI服务超时。"
        except requests.exceptions.RequestException as e:
             # Log more details for HTTP errors
             error_message = f"API 请求错误: {e}"
             if e.response is not None:
                 error_message += f" Status Code: {e.response.status_code}, Response: {e.response.text[:200]}"
             self.logger.error(error_message)
             return "抱歉，连接AI服务时出错。"
        except Exception as e:
             self.logger.error(f"解析 API 响应时出错: {e}", exc_info=True)
             return "抱歉，处理AI服务响应时出错。"
