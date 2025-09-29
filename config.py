# config.py
import os

# --- Required Environment Variables ---
# These must be set in the environment, or the bot will fail to start.
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_GROUP_ID = os.getenv("ALLOWED_GROUP_ID")
DATABASE_URL = os.getenv("DATABASE_URL")

# Admin configuration
ADMINS_STRING = os.getenv("ADMINS")
ADMINS = [admin.strip() for admin in ADMINS_STRING.split(',')] if ADMINS_STRING else []

# --- Optional Environment Variables ---
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL") # Must be like @username
SPOTIPY_CLIENT_ID = os.getenv("SPOTIPY_CLIENT_ID")
SPOTIPY_CLIENT_SECRET = os.getenv("SPOTIPY_CLIENT_SECRET")
BOT_USERNAME = os.getenv("BOT_USERNAME") # Without @
COOKIE_FILE_PATH = os.getenv("COOKIE_FILE_PATH") # Optional: Path to a cookies.txt file

# --- Bot Settings (with safe defaults) ---
UPLOAD_MODE = os.getenv("UPLOAD_MODE", "direct") # 'direct' or 'info'

# Handle boolean for QUEUE_ENABLED
raw_queue_enabled = os.getenv("QUEUE_ENABLED", "False")
QUEUE_ENABLED = raw_queue_enabled.lower() in ['true', '1', 't']

# Handle integer for AUTO_DELETE_DELAY
AUTO_DELETE_DELAY_STRING = os.getenv("AUTO_DELETE_DELAY", "0")
try:
    AUTO_DELETE_DELAY = int(AUTO_DELETE_DELAY_STRING)
except (ValueError, TypeError):
    AUTO_DELETE_DELAY = 0

# --- Sanity Checks ---
# Ensure critical variables are set, so the bot fails fast.
if not BOT_TOKEN:
    raise ValueError("FATAL: BOT_TOKEN environment variable is not set.")
if not ALLOWED_GROUP_ID:
    raise ValueError("FATAL: ALLOWED_GROUP_ID environment variable is not set.")
if not DATABASE_URL:
    raise ValueError("FATAL: DATABASE_URL environment variable is not set.")
if not ADMINS:
    raise ValueError("FATAL: ADMINS environment variable is not set or is empty.")