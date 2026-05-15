#!/usr/bin/env python3
import json
import os
import importlib.util

# Load config.py as a module without adding package to sys.path
spec = importlib.util.spec_from_file_location("botconfig", os.path.join(os.path.dirname(__file__), "..", "config.py"))
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)

appjson_path = os.path.join(os.path.dirname(__file__), "..", "app.json")

# Read existing app.json or create base
if os.path.exists(appjson_path):
    with open(appjson_path, "r", encoding="utf-8") as f:
        app = json.load(f)
else:
    app = {
        "name": "Netflix-Tv-Bot",
        "description": "Heroku app manifest",
        "repository": "",
        "env": {}
    }

env = app.setdefault("env", {})

# Helper to set value if not present or always overwrite
def set_env(key, description, value):
    env.setdefault(key, {})
    env[key]["description"] = description
    # Ensure strings for JSON
    env[key]["value"] = str(value) if value is not None else ""

set_env("API_ID", "Telegram API ID (from my.telegram.org)", getattr(config, "API_ID", ""))
set_env("API_HASH", "Telegram API hash (from my.telegram.org)", getattr(config, "API_HASH", ""))
set_env("BOT_TOKEN", "Telegram bot token (from BotFather)", getattr(config, "BOT_TOKEN", ""))
set_env("ADMINS", "Comma-separated admin user IDs (e.g. 12345,67890)", ",".join(map(str, getattr(config, "ADMINS", []))))
set_env("MONGO_URI", "MongoDB connection URI for storing data", getattr(config, "MONGO_URI", ""))
set_env("DB_NAME", "MongoDB database name", getattr(config, "DB_NAME", ""))
set_env("MAX_THREADS", "Maximum concurrent threads for processing", getattr(config, "MAX_THREADS", ""))
set_env("FORCE_SUB_CHANNEL", "Force-subscribe channel config (Name:ID or Name:ID:invite_link)", getattr(config, "FORCE_SUB_CHANNEL", ""))
set_env("FORCE_SUB_TEXT", "Message shown to users who must join channels", getattr(config, "FORCE_SUB_TEXT", ""))
set_env("LOG_CHANNEL", "Chat ID where logs are sent (negative for supergroups)", getattr(config, "LOG_CHANNEL", ""))
set_env("PORT", "Port for the web process (Heroku sets this automatically)", os.getenv("PORT", "5000"))

# Write back
with open(appjson_path, "w", encoding="utf-8") as f:
    json.dump(app, f, indent=2, ensure_ascii=False)

print("Updated app.json with values from config.py")
