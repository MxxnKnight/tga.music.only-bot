# admin_panel.py
# admin_panel.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config
import datetime

# --- Main Panel ---
def get_main_panel(context):
    """Generates the main admin panel text and keyboard."""
    text = "⚙️ *Admin Panel*\n\nSelect a setting to configure:"
    keyboard = [
        [InlineKeyboardButton("📤 Upload Mode", callback_data="admin_upload_mode")],
        [InlineKeyboardButton("🔄 Queue System", callback_data="admin_queue")],
        [InlineKeyboardButton("⏱️ Auto-Delete Delay", callback_data="admin_delay")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 Stats", callback_data="admin_stats")],
        [InlineKeyboardButton("❌ Close", callback_data="admin_close")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

# --- Upload Mode Panel ---
def get_upload_mode_panel(context):
    """Generates the upload mode settings panel."""
    current_mode = context.bot_data.get('upload_mode', config.UPLOAD_MODE)

    text = "📤 *Upload Mode Settings*\n\nSelect the default upload behavior."
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'🟢' if current_mode == 'direct' else ''} Direct",
                callback_data="admin_set_upload_direct"
            ),
            InlineKeyboardButton(
                f"{'🟢' if current_mode == 'info' else ''} Info",
                callback_data="admin_set_upload_info"
            )
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_back_to_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

# --- Stats Panel ---
def get_stats_panel(user_count):
    """Generates the stats panel."""
    text = (
        f"📊 *Bot Statistics*\n\n"
        f"Total users in database: *{user_count}*"
    )
    keyboard = [
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_back_to_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

# --- Queue System Panel ---
def get_queue_panel(context):
    """Generates the queue system settings panel."""
    queue_enabled = context.bot_data.get('queue_enabled', config.QUEUE_ENABLED)

    text = "🔄 *Queue System Settings*\n\nEnable or disable the download queue."
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'🟢' if queue_enabled else ''} Enabled",
                callback_data="admin_set_queue_enabled"
            ),
            InlineKeyboardButton(
                f"{'🟢' if not queue_enabled else ''} Disabled",
                callback_data="admin_set_queue_disabled"
            )
        ],
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_back_to_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)

# --- Auto-Delete Delay Panel ---
def get_delay_panel(context):
    """Generates the auto-delete delay settings panel."""
    delay = context.bot_data.get('auto_delete_delay', config.AUTO_DELETE_DELAY)

    text = (
        f"⏱️ *Auto-Delete Delay Settings*\n\n"
        f"Current delay: *{delay} minutes*.\n\n"
        "Reply to this message with a number to set a new delay (in minutes). "
        "Send `0` to disable auto-deletion."
    )
    keyboard = [
        [InlineKeyboardButton("⬅️ Back", callback_data="admin_back_to_main")]
    ]
    return text, InlineKeyboardMarkup(keyboard)