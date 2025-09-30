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
        [InlineKeyboardButton("🍪 Manage Cookies", callback_data="admin_cookies")],
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

# --- Cookies Panel ---
def get_cookies_panel(context):
    """Generates the cookie management panel."""
    cookie_data = context.bot_data.get('cookie_data')
    expires_at = context.bot_data.get('cookie_expires_at')

    if cookie_data and expires_at:
        now = datetime.datetime.now(expires_at.tzinfo)
        if expires_at > now:
            days_left = (expires_at - now).days
            status = f"✅ Set, expires in {days_left} days ({expires_at.strftime('%Y-%m-%d')})"
        else:
            status = "⚠️ Expired"
    else:
        status = "❌ Not set"

    text = (
        f"🍪 *Cookie Status*\n\n"
        f"Current Status: *{status}*\n\n"
        "Cookies are now managed exclusively via the `YOUTUBE_COOKIES_CONTENT` environment variable. "
        "Please update your deployment settings to change the cookies."
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