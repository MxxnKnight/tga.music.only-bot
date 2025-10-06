# start_panel.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
import config

# --- Button Definitions ---
# Define buttons to avoid repetition and ensure consistency
about_button = InlineKeyboardButton("✨ About", callback_data="start_about")
help_button = InlineKeyboardButton("❓ Help", callback_data="start_help")
tos_button = InlineKeyboardButton("📜 Terms of Service", callback_data="start_tos")
group_button = InlineKeyboardButton("👥 Join Group", url=f"https://t.me/{config.ALLOWED_GROUP_ID.replace('@', '')}")
back_button = InlineKeyboardButton("⬅️ Back to Home", callback_data="start_home")


# --- Main Start Panel (Home) ---
def get_start_panel():
    """Generates the main start panel for the bot."""
    welcome_text = (
        "👋 **Welcome to the Music Downloader Bot!**\n\n"
        "This bot can help you download songs from various sources.\n\n"
        "Use the buttons below to learn more or join our group to start downloading."
    )
    # Home panel shows all main options
    keyboard = [
        [about_button, help_button],
        [tos_button, group_button]
    ]
    return welcome_text, InlineKeyboardMarkup(keyboard)

# --- About Panel ---
def get_about_panel():
    """Generates the 'About' panel and its interconnected keyboard."""
    about_text = (
        "✨ **About This Bot**\n\n"
        "This bot was created to make downloading your favorite music easy and fast.\n\n"
        "- **Hosted on:** Render\n"
        f"- **Owner:** {config.OWNER_NAME}\n"
        "- **Language:** Python\n"
        "- **Library:** `python-telegram-bot`"
    )
    # Keyboard for 'About' page doesn't show the 'About' button
    keyboard = [
        [help_button, tos_button],
        [back_button]
    ]
    return about_text, InlineKeyboardMarkup(keyboard)

# --- Help Panel ---
def get_help_panel():
    """Generates the 'Help' panel and its interconnected keyboard."""
    help_text = (
        "❓ **How to Use the Bot**\n\n"
        "1. **Join the Group:** You can only request songs in our official group. Click the 'Join Group' button on the main menu.\n"
        "2. **Request a Song:** Simply send the name of a song (e.g., 'Never Gonna Give You Up') or a link from YouTube, Spotify, or JioSaavn.\n"
        "3. **Download:** The bot will process your request and send you the audio file.\n\n"
        "If you encounter any issues, please report them in the group."
    )
    # Keyboard for 'Help' page doesn't show the 'Help' button
    keyboard = [
        [about_button, tos_button],
        [back_button]
    ]
    return help_text, InlineKeyboardMarkup(keyboard)

# --- TOS Panel ---
def get_tos_panel():
    """Generates the 'Terms of Service' panel and its interconnected keyboard."""
    tos_text = (
        "📜 **Terms of Service**\n\n"
        "1. **Personal Use Only:** This service is for personal, non-commercial use only. Do not use it for piracy or illegal distribution of copyrighted content.\n"
        "2. **No Guarantees:** The bot is provided as-is. We do not guarantee its availability or functionality at all times.\n"
        "3. **Respect Copyright:** You are responsible for ensuring that you have the right to download the content you request. The bot owner is not liable for any copyright infringement.\n"
        "4. **Usage Limits:** To ensure fair usage, we may impose limits on the number of requests per user.\n\n"
        "By using this bot, you agree to these terms."
    )
    # Keyboard for 'TOS' page doesn't show the 'TOS' button
    keyboard = [
        [about_button, help_button],
        [back_button]
    ]
    return tos_text, InlineKeyboardMarkup(keyboard)