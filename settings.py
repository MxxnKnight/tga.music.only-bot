# settings.py
import json
import logging
import config

logger = logging.getLogger(__name__)
SETTINGS_FILE = "settings.json"

DEFAULT_SETTINGS = {
    "upload_mode": config.UPLOAD_MODE,
    "queue_enabled": config.QUEUE_ENABLED,
    "auto_delete_delay": config.AUTO_DELETE_DELAY,
}

def load_settings() -> dict:
    """Loads settings from the JSON file, or returns defaults if it doesn't exist."""
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
            # Ensure all default keys are present
            for key, value in DEFAULT_SETTINGS.items():
                settings.setdefault(key, value)
            return settings
    except (FileNotFoundError, json.JSONDecodeError):
        logger.warning(f"'{SETTINGS_FILE}' not found or invalid. Creating with default settings.")
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS

def save_settings(settings: dict):
    """Saves the given settings dictionary to the JSON file."""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        logger.error(f"Failed to save settings to '{SETTINGS_FILE}': {e}")