#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import pandas as pd
from datetime import datetime
import glob # For finding log files
import re # For regex potentially

from modules.config import Config
from modules.logger import Logger # Optional: for logging export process
from modules.ai_model import AIModel

# --- Configuration Loading ---
def load_configuration(config_file='config.json'):
    """Loads configuration specifically for the export script."""
    config = Config(config_file)
    export_config = config.get(section='export', default={})
    ai_config = config.get(section='ai_model', default={})
    log_config = config.get(section='logger', default={})
    return export_config, ai_config, log_config

# --- Message Categorization ---
def categorize_message(message, export_config):
    """Categorizes a message based on keywords defined in export_config."""
    text = message.lower() # Case-insensitive matching

    roadshow_kws = export_config.get('roadshow_keywords', [])
    appointment_kws = export_config.get('appointment_keywords', [])
    opinion_kws = export_config.get('opinion_keywords', [])

    # Check for Tencent meeting link pattern (example)
    if re.search(r'https://meeting.tencent.com/\S+', text):
        return "路演信息"
        
    # Check keywords, prioritizing Roadshow > Appointment > Opinion
    if any(kw in text for kw in roadshow_kws):
        return "路演信息"
    if any(kw in text for kw in appointment_kws):
        return "调研预约"
    if any(kw in text for kw in opinion_kws):
        return "观点与讨论"

    return "其他"

# --- Log Processing --- 
def process_log_files(log_dir, export_config):
    """Reads all chat*.json logs, categorizes messages, and returns data."""
    all_data = []
    messages_by_category = {
        "路演信息": [],
        "调研预约": [],
        "观点与讨论": [],
        "其他": []
    }
    
    chat_log_pattern = os.path.join(log_dir, 'chats', 'chat_*.json')
    log_files = glob.glob(chat_log_pattern)
    
    print(f"Found {len(log_files)} chat log files in {os.path.join(log_dir, 'chats')}")

    for file_path in sorted(log_files): # Process in chronological order
        print(f"Processing log file: {file_path}...")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                chat_history = json.load(f)
                if not isinstance(chat_history, list):
                    print(f"  Warning: Invalid format in {file_path}, expected a list. Skipping.")
                    continue
                    
                for entry in chat_history:
                    if isinstance(entry, dict) and 'timestamp' in entry and 'message' in entry and 'reply' in entry:
                        message_text = entry['message']
                        category = categorize_message(message_text, export_config)
                        
                        all_data.append({
                            'Timestamp': entry['timestamp'],
                            'Original Message': message_text,
                            'Reply': entry['reply'],
                            'Category': category
                        })
                        
                        # Add original message to category list for summarization
                        if category != "其他":
                             messages_by_category[category].append(message_text)
                    else:
                         print(f"  Warning: Skipping invalid entry in {file_path}: {entry}")
                         
        except json.JSONDecodeError:
            print(f"  Error: Could not decode JSON from {file_path}. Skipping.")
        except Exception as e:
            print(f"  Error processing file {file_path}: {e}")
            
    return all_data, messages_by_category

# --- Summarization --- 
def summarize_categories(messages_by_category, ai_model, export_config, logger):
    """Uses the AI model to summarize messages for relevant categories."""
    summaries = {}
    prompt_template = export_config.get('summarize_prompt_template', "请总结以下关于{category}的聊天记录要点：\\n\\n{messages}")
    max_messages = export_config.get('max_messages_for_summary', 100)

    for category, messages in messages_by_category.items():
        if category == "其他" or not messages:
            continue
            
        logger.info(f"Summarizing category: {category} ({len(messages)} messages)")
        
        # Limit the number of messages to avoid overly long prompts/context issues
        messages_to_summarize = messages[-max_messages:] # Take the most recent messages
        combined_text = "\\n".join([f"- {msg}" for msg in messages_to_summarize])
        
        prompt = prompt_template.format(category=category, messages=combined_text)
        
        # Use the AI model's generate_reply function
        # We might need to specify which model to use if the config differentiates them
        summary = ai_model.generate_reply(prompt) # Pass only the prompt
        
        if summary and "抱歉" not in summary: # Basic check for failed summary
            summaries[category] = summary
            logger.info(f"  Summary generated for {category}.")
        else:
            logger.error(f"  Failed to generate summary for {category}. Response: {summary}")
            summaries[category] = "Failed to generate summary."
            
    return summaries

# --- Excel Export --- 
def export_to_excel(all_data, summaries, output_file):
    """Exports the categorized data and summaries to an Excel file."""
    try:
        df = pd.DataFrame(all_data)
        summary_df = pd.DataFrame(list(summaries.items()), columns=['Category', 'Summary'])

        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Categorized Logs', index=False)
            summary_df.to_excel(writer, sheet_name='Summaries', index=False)
        
        print(f"Successfully exported logs and summaries to {output_file}")
        
    except Exception as e:
        print(f"Error exporting to Excel file {output_file}: {e}")

# --- Main Execution --- 
if __name__ == "__main__":
    print("Starting chat log export and summarization...")
    
    # Load configurations
    export_cfg, ai_cfg, log_cfg = load_configuration()
    output_file = export_cfg.get('output_file', 'chat_log_export.xlsx')
    log_dir = log_cfg.get('log_dir', 'logs')

    # Initialize logger (optional for this script)
    exporter_logger = Logger(log_cfg) # Use the same logger config
    exporter_logger.info("====== Log Export Started ======")

    # Initialize AI Model (needed for summarization)
    # Make sure AI config has necessary keys (api_key, api_url, model_name)
    ai_model = AIModel(exporter_logger, ai_cfg)

    # Process log files
    categorized_data, messages_by_cat = process_log_files(log_dir, export_cfg)

    if not categorized_data:
        print("No chat data found or processed. Exiting.")
        exporter_logger.warning("No chat data processed during export.")
    else:
        # Generate summaries
        category_summaries = summarize_categories(messages_by_cat, ai_model, export_cfg, exporter_logger)
        
        # Export to Excel
        export_to_excel(categorized_data, category_summaries, output_file)

    exporter_logger.info("====== Log Export Finished ======")
    print("Export process finished.")