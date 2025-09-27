# config.py
import os

# Helper function to get config from environment variables
def get_env(name, default):
    return os.environ.get(name, default)

# --- Required Environment Variables ---
BOT_TOKEN = get_env("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
ALLOWED_GROUP_ID = get_env("ALLOWED_GROUP_ID", "YOUR_ALLOWED_GROUP_ID")
ADMINS_STRING = get_env("ADMINS", "ADMIN_USER_ID_1,ADMIN_USER_ID_2")
ADMINS = [admin.strip() for admin in ADMINS_STRING.split(',')]

# --- Optional Environment Variables ---
FORCE_SUB_CHANNEL = get_env("FORCE_SUB_CHANNEL", None) # Must be like @username
SPOTIPY_CLIENT_ID = get_env("SPOTIPY_CLIENT_ID", None)
SPOTIPY_CLIENT_SECRET = get_env("SPOTIPY_CLIENT_SECRET", None)
BOT_USERNAME = get_env("BOT_USERNAME", "YOUR_BOT_USERNAME") # Without @

# --- Database URL (Important for persistence) ---
DATABASE_URL = get_env("DATABASE_URL", "postgresql://user:password@host:port/database")

# --- Bot Settings (with defaults) ---
UPLOAD_MODE = get_env("UPLOAD_MODE", "direct") # 'direct' or 'info'

# Handle boolean for QUEUE_ENABLED
raw_queue_enabled = get_env("QUEUE_ENABLED", "False")
QUEUE_ENABLED = raw_queue_enabled.lower() in ['true', '1', 't']

# Handle integer for AUTO_DELETE_DELAY
AUTO_DELETE_DELAY_STRING = get_env("AUTO_DELETE_DELAY", "0")
try:
    AUTO_DELETE_DELAY = int(AUTO_DELETE_DELAY_STRING)
except ValueError:
    AUTO_DELETE_DELAY = 0