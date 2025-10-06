# bot.py
import logging
import config
import os
import re
import yt_dlp
import spotipy
import asyncio
import db
import admin_panel
import start_panel
import functools
import datetime
import time
import threading
from datetime import timedelta
from spotipy.oauth2 import SpotifyClientCredentials
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from telegram.error import TimedOut, BadRequest, RetryAfter

# --- Global Variables ---
last_update_time = 0

# --- Flask App for Health Check ---
flask_app = Flask(__name__)

@flask_app.route('/')
def health_check():
    """A simple health check endpoint for Render."""
    return "Bot is running!", 200

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Spotify setup (with error handling for missing credentials)
spotify = None
if config.SPOTIPY_CLIENT_ID and config.SPOTIPY_CLIENT_SECRET:
    try:
        spotify = spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=config.SPOTIPY_CLIENT_ID, 
                client_secret=config.SPOTIPY_CLIENT_SECRET
            )
        )
        logger.info("Spotify integration enabled")
    except Exception as e:
        logger.warning(f"Spotify initialization failed: {e}")
else:
    logger.warning("Spotify credentials not provided. Spotify links will not work.")

# Conversation states for Admin Panel
SELECTING_ACTION, SETTING_DELAY, BROADCASTING_MESSAGE, BROADCASTING_CONFIRM = range(4)

COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")

# --- Job Queue Callbacks ---
async def delete_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes a message specified in the job context."""
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data['message_id'])
        logger.info(f"Auto-deleted message {job.data['message_id']} in chat {job.chat_id}")
    except Exception as e:
        logger.error(f"Failed to delete message {job.data['message_id']} in chat {job.chat_id}: {e}")



# --- Queue System ---
download_queue = asyncio.Queue()

async def queue_worker(application: Application):
    """Worker that processes the download queue."""
    logger.info("Queue worker started.")
    while True:
        try:
            item = await download_queue.get()
            update, info, message = item['update'], item['info'], item['message']

            try:
                await download_and_send_song(update, application, info, message)
            except Exception as e:
                logger.error(f"Error processing item from queue: {e}", exc_info=True)
                try:
                    await message.edit_text("Sorry, an error occurred while processing your request from the queue.")
                except:
                    pass
            finally:
                download_queue.task_done()
        except asyncio.CancelledError:
            logger.info("Queue worker cancelled")
            break
        except Exception as e:
            logger.error(f"Unexpected error in queue worker: {e}", exc_info=True)

async def start_queue_worker(application: Application) -> None:
    """Starts the queue worker as a background task."""
    task = asyncio.create_task(queue_worker(application))
    application.bot_data['queue_worker_task'] = task

# --- Admin and Helper Functions ---
def get_ydl_opts(base_opts=None):
    """Creates yt-dlp options, adding cookie file if it exists."""
    if base_opts is None:
        base_opts = {}

    final_opts = base_opts.copy()

    if os.path.exists(COOKIE_FILE):
        final_opts['cookiefile'] = COOKIE_FILE
        logger.info(f"✅ Using cookie file at: {COOKIE_FILE}")
    else:
        logger.warning(f"⚠️ No cookie file found at {COOKIE_FILE}")

    return final_opts

def generate_progress_bar(percentage):
    """Generates a text-based progress bar."""
    if percentage is None:
        return ""
    filled_length = int(percentage / 10)
    bar = '█' * filled_length + '░' * (10 - filled_length)
    return f"[{bar}] {percentage:.1f}%"

def is_admin(user_id: int) -> bool:
    """Check if a user is an admin."""
    return str(user_id) in config.ADMINS

async def is_user_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Check if a user is subscribed to the force-sub channel."""
    if not config.FORCE_SUB_CHANNEL:
        return True
    try:
        member = await context.bot.get_chat_member(chat_id=config.FORCE_SUB_CHANNEL, user_id=user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Error checking subscription for user {user_id} in {config.FORCE_SUB_CHANNEL}: {e}")
        return False

# --- Main Command Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private':
        await db.add_user(user_id)
        args = context.args
        if args and args[0].startswith("get_song_"):
            video_id = args[0].split("_", 2)[2]
            await send_song_in_pm(update, context, video_id)
        else:
            text, keyboard = start_panel.get_start_panel()
            await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        if str(update.effective_chat.id) == config.ALLOWED_GROUP_ID:
            await update.message.reply_text("Hi! I'm ready to download music. Send me a song name or a link.")
        else:
            await update.message.reply_text("This group is not authorized to use this bot.")

# --- Admin Panel Conversation ---
async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays the main admin panel and enters the conversation."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    text, keyboard = admin_panel.get_main_panel(context)

    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        if 'panel_message_id' in context.user_data:
            try:
                await context.bot.delete_message(update.effective_chat.id, context.user_data['panel_message_id'])
            except Exception:
                pass

        message = await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        context.user_data['panel_message_id'] = message.message_id

    return SELECTING_ACTION

async def admin_panel_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles callbacks for navigating the admin panel."""
    query = update.callback_query
    await query.answer()
    data = query.data

    async def update_and_show_panel(panel_function):
        text, keyboard = panel_function(context)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    if data == "admin_back_to_main":
        await update_and_show_panel(admin_panel.get_main_panel)
        return SELECTING_ACTION

    elif data == "admin_upload_mode":
        await update_and_show_panel(admin_panel.get_upload_mode_panel)
    elif data.startswith("admin_set_upload_"):
        mode = data.split('_')[-1]
        context.bot_data['upload_mode'] = mode
        await db.set_setting('upload_mode', mode)
        await update_and_show_panel(admin_panel.get_upload_mode_panel)
    elif data == "admin_queue":
        await update_and_show_panel(admin_panel.get_queue_panel)
    elif data.startswith("admin_set_queue_"):
        status = data.split('_')[-1] == 'enabled'
        context.bot_data['queue_enabled'] = status
        await db.set_setting('queue_enabled', status)
        await update_and_show_panel(admin_panel.get_queue_panel)
    elif data == "admin_stats":
        user_count = await db.get_users_count()
        text, keyboard = admin_panel.get_stats_panel(user_count)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    elif data == "admin_close":
        await query.edit_message_text("Admin panel closed.")
        context.user_data.clear()
        return ConversationHandler.END
    elif data == "admin_delay":
        text, keyboard = admin_panel.get_delay_panel(context)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return SETTING_DELAY
    elif data == "admin_broadcast":
        await query.edit_message_text("Please send the message you want to broadcast now.\n\nTo cancel, use /cancel.")
        return BROADCASTING_MESSAGE


    return SELECTING_ACTION

async def set_delay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the admin's reply to set the delay."""
    try:
        delay = int(update.message.text)
        if delay < 0:
            await update.message.reply_text("Please provide a non-negative number.")
            return SETTING_DELAY

        context.bot_data['auto_delete_delay'] = delay
        await db.set_setting('auto_delete_delay', delay)

        await update.message.reply_text(f"✅ Auto-delete delay set to {delay} minutes." if delay > 0 else "✅ Auto-deletion disabled.")
    except (ValueError):
        await update.message.reply_text("Invalid number. Please send a valid number of minutes.")
        return SETTING_DELAY

    # Return to main panel
    text, keyboard = admin_panel.get_main_panel(context)
    await context.bot.edit_message_text(
        text=text,
        chat_id=update.effective_chat.id,
        message_id=context.user_data['panel_message_id'],
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN
    )
    return SELECTING_ACTION

async def broadcast_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the message to be broadcasted."""
    context.user_data['broadcast_message_id'] = update.message.message_id
    context.user_data['broadcast_chat_id'] = update.message.chat_id

    keyboard = [
        [InlineKeyboardButton("To All Users", callback_data="broadcast_users")],
        [InlineKeyboardButton("To Group", callback_data="broadcast_group")],
        [InlineKeyboardButton("⬅️ Back to Panel", callback_data="admin_back_to_main")]
    ]
    await update.message.reply_text(
        "Message received. Where do you want to broadcast it?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BROADCASTING_CONFIRM

async def broadcast_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the broadcast confirmation and sends the message."""
    query = update.callback_query
    await query.answer()
    broadcast_type = query.data

    if broadcast_type == "admin_back_to_main":
        await panel_command(update, context)
        return SELECTING_ACTION

    message_id = context.user_data.get('broadcast_message_id')
    chat_id = context.user_data.get('broadcast_chat_id')
    if not message_id or not chat_id:
        await query.edit_message_text("Error: Could not find the message. Returning to panel.")
        await asyncio.sleep(2)
        await panel_command(update, context)
        return SELECTING_ACTION

    await query.edit_message_text("Starting broadcast...")

    target_chats = []
    if broadcast_type == 'broadcast_users':
        target_chats = await db.get_all_users()
    elif broadcast_type == 'broadcast_group':
        target_chats = [int(config.ALLOWED_GROUP_ID)]

    success_count, fail_count = 0, 0
    for target_chat_id in target_chats:
        try:
            await context.bot.copy_message(chat_id=target_chat_id, from_chat_id=chat_id, message_id=message_id)
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to send broadcast to {target_chat_id}: {e}")

    await query.edit_message_text(f"Broadcast complete.\n- Sent: {success_count}\n- Failed: {fail_count}")
    await asyncio.sleep(3)
    await panel_command(update, context)
    return SELECTING_ACTION

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    if 'panel_message_id' in context.user_data:
        try:
            await context.bot.edit_message_text(
                "Admin panel cancelled and closed.",
                chat_id=update.effective_chat.id,
                message_id=context.user_data['panel_message_id']
            )
        except Exception:
            await update.message.reply_text("Admin panel cancelled and closed.")
    else:
        await update.message.reply_text("Action cancelled.")

    context.user_data.clear()
    return ConversationHandler.END


# --- Start Panel Callback ---
async def start_panel_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles callbacks for the start panel."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # A helper function to avoid repeating code
    async def update_and_show_panel(panel_function):
        text, keyboard = panel_function()
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    if data == "start_home":
        await update_and_show_panel(start_panel.get_start_panel)
    elif data == "start_about":
        await update_and_show_panel(start_panel.get_about_panel)
    elif data == "start_help":
        await update_and_show_panel(start_panel.get_help_panel)
    elif data == "start_tos":
        await update_and_show_panel(start_panel.get_tos_panel)


# --- Song Handling Logic ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private': 
        await db.add_user(user_id)
    if str(update.effective_chat.id) != config.ALLOWED_GROUP_ID and update.effective_chat.type != 'private': 
        return
    if update.effective_chat.type == 'private':
        await update.message.reply_text("Sorry, you can't request songs directly in PM. Please use the allowed group.")
        return
    
    message_text = update.message.text
    url_pattern = re.compile(r'https?://\S+')
    query = message_text
    message = await update.message.reply_text("Processing...")
    
    if url_pattern.match(message_text):
        if "spotify.com" in message_text:
            if not spotify:
                await message.edit_text("Spotify integration is not configured.")
                return
            try:
                track = spotify.track(message_text)
                query = f"{track['name']} {track['artists'][0]['name']}"
                await message.edit_text("🎧 Downloading from Spotify...")
            except Exception as e:
                logger.error(f"Spotify error: {e}")
                await message.edit_text("Could not process the Spotify link.")
                return
        elif "jiosaavn.com" in message_text:
            await message.edit_text("🎧 Downloading from Saavn...")
            song_name_match = re.search(r'/song/[^/]+/([^/?]+)', message_text)
            if song_name_match:
                query = song_name_match.group(1).replace('-', ' ')
            else:
                await message.edit_text("Could not extract info from Saavn link.")
                return
    
    await process_song_request(update, context, query, message)

async def process_song_request(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, message):
    base_ydl_opts = {'format': 'bestaudio[ext=m4a]/bestaudio', 'noplaylist': True, 'default_search': 'ytsearch1'}
    ydl_opts = get_ydl_opts(base_ydl_opts)
    try:
        # Distinguish between a URL and a search query
        url_pattern = re.compile(r'https?://\S+')
        search_query = query if url_pattern.match(query) else f"ytsearch:{query}"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)

            # Handle different types of results from yt-dlp
            if 'entries' in info:
                # It's a playlist (e.g., from a search)
                if info['entries']:
                    # Playlist has videos, take the first one
                    info = info['entries'][0]
                else:
                    # Playlist is empty (no search results)
                    await message.edit_text("Sorry, I couldn't find a song with that name.")
                    return
            # If 'entries' is not in info, it's a direct link to a single video,
            # so the info object is already correct. We do nothing.

            video_id = info.get('id')
            if not video_id:
                await message.edit_text("Sorry, I could not get a valid ID for the song.")
                return

            if context.bot_data.get('upload_mode') == 'direct':
                if await is_user_subscribed(update.effective_user.id, context):
                    if context.bot_data.get('queue_enabled'):
                        await download_queue.put({'update': update, 'info': info, 'message': message})
                        await message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
                    else:
                        await download_and_send_song(update, context.application, info, message)
                else:
                    keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")], [InlineKeyboardButton("Try Again", callback_data=f"checksub_{video_id}")]]
                    await message.edit_text("You must subscribe to our channel to download songs directly.", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                title, artist, album = info.get('title', 'Unknown Title'), info.get('uploader', 'Unknown Artist'), info.get('album', None)
                caption = f"🎵 **{title}**\n👤 **{artist}**" + (f"\n💿 **{album}**" if album else "")

                if config.BOT_USERNAME:
                    keyboard = [[InlineKeyboardButton("Get Song", url=f"https://t.me/{config.BOT_USERNAME}?start=get_song_{video_id}")]]
                    await message.edit_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
                else:
                    await message.edit_text(f"{caption}\n\n⚠️ Bot username not configured. Cannot provide download link.")
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await message.edit_text("Could not find the song or an error occurred.")

async def checksub_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    video_id = query.data.split("_", 1)[1]
    
    if await is_user_subscribed(query.from_user.id, context):
        await query.message.edit_text("Thank you for subscribing! Processing request...")

        # Re-fetch info since it's not cached
        base_ydl_opts = {'format': 'bestaudio[ext=m4a]/bestaudio', 'noplaylist': True}
        ydl_opts = get_ydl_opts(base_ydl_opts)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_id, download=False)

            if context.bot_data.get('queue_enabled'):
                await download_queue.put({'update': update, 'info': info, 'message': query.message})
                await query.message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
            else:
                await download_and_send_song(update, context.application, info, query.message)
        except Exception as e:
            logger.error(f"Error re-fetching info for checksub: {e}")
            await query.message.edit_text("Sorry, the song request expired or failed.")
    else:
        await query.message.edit_text("You are still not subscribed. Please join the channel and try again.")

async def send_song_in_pm(update: Update, context: ContextTypes.DEFAULT_TYPE, video_id: str):
    await db.add_user(update.effective_user.id)

    if await is_user_subscribed(update.effective_user.id, context):
        message = await update.message.reply_text("Processing your request...")

        base_ydl_opts = {'format': 'bestaudio[ext=m4a]/bestaudio', 'noplaylist': True}
        ydl_opts = get_ydl_opts(base_ydl_opts)
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_id, download=False)

            if context.bot_data.get('queue_enabled'):
                await download_queue.put({'update': update, 'info': info, 'message': message})
                await message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
            else:
                await download_and_send_song(update, context.application, info, message)
        except Exception as e:
            logger.error(f"Error fetching info for PM song: {e}", exc_info=True)
            await message.edit_text("Sorry, the song request expired or failed.")
    else:
        if config.FORCE_SUB_CHANNEL:
            keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")]]
            await update.message.reply_text("You must subscribe to our channel to get the song.", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("Force subscription is not configured.")

def _blocking_download_and_process(ydl_opts, info, download_path, base_filename):
    """
    Handles the blocking I/O tasks: downloading, processing, and reading files.
    This function is designed to be run in a separate thread.
    """
    # Ensure the download directory exists.
    # This is especially important for the RAM disk, which might not persist.
    os.makedirs(download_path, exist_ok=True)

    logger.info(f"Starting download with yt-dlp options: {ydl_opts}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([info['webpage_url']])
        logger.info("yt-dlp download completed successfully.")
    except yt_dlp.utils.DownloadError as e:
        logger.error(f"yt-dlp failed with a DownloadError: {e}")
        raise e

    downloaded_file = None
    for file in os.listdir(download_path):
        if file.startswith(base_filename) and file.split('.')[-1] in ['m4a', 'webm']:
            downloaded_file = os.path.join(download_path, file)
            break

    if not downloaded_file or not os.path.exists(downloaded_file):
        raise FileNotFoundError(f"Downloaded audio file not found for base name {base_filename} in {download_path}")

    with open(downloaded_file, 'rb') as f:
        audio_bytes = f.read()

    thumbnail_path = None
    for file in os.listdir(download_path):
        if file.startswith(base_filename) and file.split('.')[-1] in ['jpg', 'jpeg', 'png', 'webp']:
            thumbnail_path = os.path.join(download_path, file)
            break

    thumbnail_bytes = None
    if thumbnail_path and os.path.exists(thumbnail_path):
        with open(thumbnail_path, 'rb') as art:
            thumbnail_bytes = art.read()
        logger.info(f"Read thumbnail into bytes from {thumbnail_path}")

    return downloaded_file, thumbnail_path, thumbnail_bytes, audio_bytes

def _blocking_cleanup(paths_to_clean):
    """
    Handles the blocking I/O task of cleaning up files.
    This function is designed to be run in a separate thread.
    """
    for path in paths_to_clean:
        if not path or not os.path.exists(path):
            continue
        try:
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                if not os.listdir(path):
                    os.rmdir(path)
        except Exception as e:
            logger.error(f"Error during cleanup of {path}: {e}")


async def download_and_send_song(update: Update, application: Application, info: dict, message):
    loop = asyncio.get_running_loop()
    chat_id = message.chat_id
    video_id = info.get('id')

    # --- Check Cache First ---
    if video_id:
        cached_file_id = await db.get_from_cache(video_id)
        if cached_file_id:
            logger.info(f"Found cached file_id {cached_file_id} for video {video_id}. Sending from cache.")
            try:
                title = info.get('title', 'Unknown Title')
                artist = info.get('uploader', 'Unknown Artist')
                duration = info.get('duration', 0)
                album = info.get('album', None)
                caption = f"🎵 **{title}**\n👤 **{artist}**" + (f"\n💿 **{album}**" if album else "")
                delay = int(application.bot_data.get('auto_delete_delay', 0))
                if delay > 0:
                    caption += f"\n\n⚠️ *This file will be deleted in {delay} minutes.*"

                sent_message = await application.bot.send_audio(
                    chat_id=chat_id,
                    audio=cached_file_id,
                    caption=caption,
                    title=title,
                    performer=artist,
                    duration=duration,
                    parse_mode=ParseMode.MARKDOWN,
                )

                if delay > 0:
                    application.job_queue.run_once(
                        delete_message_job,
                        when=timedelta(minutes=delay),
                        data={'message_id': sent_message.message_id},
                        chat_id=chat_id
                    )

                await message.delete()
                return
            except Exception as e:
                logger.error(f"Failed to send from cache with file_id {cached_file_id}: {e}. Falling back to download.", exc_info=True)

    # --- Use RAM disk if available, otherwise fallback to local disk ---
    if os.path.exists("/dev/shm") and os.access("/dev/shm", os.W_OK):
        download_path = os.path.join('/dev/shm', str(chat_id))
        logger.info("Using RAM disk for download: /dev/shm")
    else:
        download_path = os.path.join('downloads', str(chat_id))
        logger.info("RAM disk not available, using local disk for download.")

    base_filename = info['id']
    outtmpl = os.path.join(download_path, f"{base_filename}.%(ext)s")
    last_update_time = 0

    async def edit_message_safe(text):
        """Safely edit the message, handling potential rate limits."""
        try:
            await message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
        except RetryAfter as e:
            logger.warning(f"Rate limited. Retrying after {e.retry_after} seconds.")
            await asyncio.sleep(e.retry_after)
            await edit_message_safe(text) # Retry the edit
        except BadRequest as e:
            # Ignore "message is not modified" error, log others
            if "not modified" not in str(e):
                logger.warning(f"Could not edit message {message.message_id}: {e}")

    def progress_hook(d):
        nonlocal last_update_time
        if d['status'] == 'downloading':
            current_time = time.time()
            if current_time - last_update_time < 2:
                return

            percentage = d.get('_percent_str', '0%')
            # remove ANSI escape codes
            percentage = re.sub(r'\x1b\[[0-9;]*m', '', percentage).replace('%', '')
            try:
                percentage = float(percentage)
            except (ValueError, TypeError):
                return

            speed = d.get('speed', 0)
            if speed is None: speed = 0
            speed_str = f"{speed / 1024 / 1024:.2f} MB/s"
            total_bytes = d.get('total_bytes')
            if total_bytes is None:
                total_bytes_str = "Unknown"
            else:
                total_bytes_str = f"{total_bytes / 1024 / 1024:.2f} MB"

            progress_bar = generate_progress_bar(percentage)
            text = (
                f"**Downloading...**\n"
                f"`{progress_bar}`\n"
                f"**Progress:** {percentage:.1f}%\n"
                f"**Size:** {total_bytes_str}\n"
                f"**Speed:** {speed_str}"
            )

            future = asyncio.run_coroutine_threadsafe(edit_message_safe(text), loop)
            future.result() # Wait for the coroutine to finish
            last_update_time = current_time

    base_ydl_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio',
        'outtmpl': outtmpl,
        'noplaylist': True,
        'writethumbnail': True,
        'progress_hooks': [progress_hook],
    }
    ydl_opts = get_ydl_opts(base_ydl_opts)

    downloaded_file = None
    thumbnail_path = None

    try:
        await edit_message_safe("Initializing download...")

        blocking_task = functools.partial(_blocking_download_and_process, ydl_opts, info, download_path, base_filename)
        downloaded_file, thumbnail_path, thumbnail_bytes, audio_bytes = await loop.run_in_executor(None, blocking_task)

        await edit_message_safe("Download complete. Now uploading...")
        title = info.get('title', 'Unknown Title')
        artist = info.get('uploader', 'Unknown Artist')
        duration = info.get('duration', 0)
        album = info.get('album', None)

        caption = f"🎵 **{title}**\n👤 **{artist}**" + (f"\n💿 **{album}**" if album else "")
        delay = int(application.bot_data.get('auto_delete_delay', 0))
        if delay > 0:
            caption += f"\n\n⚠️ *This file will be deleted in {delay} minutes.*"

        file_size = os.path.getsize(downloaded_file)
        logger.info(f"File size: {file_size / (1024*1024):.2f} MB")

        if file_size > 50 * 1024 * 1024:
            await message.edit_text("❌ File is too large for Telegram (>50MB)")
            return

        try:
            sent_message = await application.bot.send_audio(
                chat_id=chat_id,
                audio=audio_bytes,
                caption=caption,
                title=title,
                performer=artist,
                duration=duration,
                parse_mode=ParseMode.MARKDOWN,
                thumbnail=thumbnail_bytes
            )
            # Add the file_id to the cache for future use
            await db.add_to_cache(video_id=info['id'], file_id=sent_message.audio.file_id)
            logger.info(f"Cached file_id {sent_message.audio.file_id} for video {info['id']}")

        except TimedOut:
            logger.error(f"Upload timed out for {downloaded_file} after 600 seconds.")
            await message.edit_text("❌ Upload timed out. The file might be too large or the connection is slow.")
            return

        if delay > 0:
            application.job_queue.run_once(
                delete_message_job,
                when=timedelta(minutes=delay),
                data={'message_id': sent_message.message_id},
                chat_id=chat_id
            )

        try:
            await message.delete()
        except BadRequest:
            logger.warning(f"Could not delete message {message.message_id} in chat {chat_id}, it was likely already deleted.")
            pass

    except Exception as e:
        logger.error("Error in download_and_send_song", exc_info=True)
        error_message = str(e).lower()
        if "login" in error_message or "sign in" in error_message or "authentication" in error_message or "403" in error_message or "access denied" in error_message:
            logger.warning("Download failed, possibly due to expired cookies. Notifying admins.")
            notification = "🚨 **Download Failed: Possible Cookie Issue** 🚨\n\nA download failed with an authentication error. Your cookies may have expired or be invalid. Please update them via the admin panel."
            for admin_id in config.ADMINS:
                try:
                    await application.bot.send_message(chat_id=int(admin_id), text=notification, parse_mode=ParseMode.MARKDOWN)
                except Exception as admin_e:
                    logger.error(f"Failed to send cookie error warning to admin {admin_id}: {admin_e}")
            try:
                await message.edit_text("Sorry, a download error occurred. The admins have been notified if this looks like a cookie issue.")
            except:
                pass
        else:
            try:
                await message.edit_text(f"❌ Upload failed: {str(e)[:100]}")
            except:
                pass
    finally:
        paths_to_clean = [downloaded_file, thumbnail_path, download_path]
        cleanup_task = functools.partial(_blocking_cleanup, paths_to_clean)
        await loop.run_in_executor(None, cleanup_task)


def run_flask_app():
    """Runs the Flask app in a separate thread."""
    port = int(os.environ.get('PORT', 8080))
    flask_app.run(host='0.0.0.0', port=port)

async def main() -> None:
    """Initializes, configures, and runs the bot."""
    logger.info("Starting bot initialization...")

    # --- Run Flask app in a background thread ---
    flask_thread = threading.Thread(target=run_flask_app)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Flask health check server running in a background thread.")

    # --- Cookie File Check ---
    if os.path.exists(COOKIE_FILE):
        logger.info(f"Cookie file found at: {COOKIE_FILE}")
    else:
        logger.warning(f"Cookie file not found at: {COOKIE_FILE}. Downloads requiring authentication may fail.")

    # --- Initialization ---
    await db.initialize_db()


    try:
        loaded_settings = await db.load_all_settings()
        logger.info(f"Loaded settings: {loaded_settings}")

        # --- Application Setup ---
        application = (
            Application.builder()
            .token(config.BOT_TOKEN)
            .connect_timeout(60)
            .read_timeout(600)
            .write_timeout(600)
            .pool_timeout(60)
            .post_init(start_queue_worker)
            .build()
        )

        # Load the persistent settings into the bot
        application.bot_data.update(loaded_settings)

        # --- Command and Message Handlers ---
        admin_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("panel", panel_command)],
            states={
                SELECTING_ACTION: [CallbackQueryHandler(admin_panel_actions)],
                SETTING_DELAY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, set_delay_handler),
                    CallbackQueryHandler(admin_panel_actions, pattern='^admin_back_to_main$')
                ],
                BROADCASTING_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_message_handler)],
                BROADCASTING_CONFIRM: [CallbackQueryHandler(broadcast_confirmation_handler)],
            },
            fallbacks=[CommandHandler("cancel", cancel_command)],
            per_message=False,
            name="admin_panel_conversation",
            allow_reentry=True
        )

        application.add_handler(CommandHandler("start", start))
        application.add_handler(admin_conv_handler)
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(CallbackQueryHandler(checksub_callback_handler, pattern='^checksub_.*'))
        application.add_handler(CallbackQueryHandler(start_panel_callback_handler, pattern='^start_.*'))

        # --- Schedule recurring jobs ---

        # --- Run the Bot ---
        logger.info("Starting bot polling...")
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)

        # Keep the bot running
        await asyncio.Event().wait()

    except (KeyboardInterrupt, SystemExit):
        logger.info("Received stop signal")
    finally:
        # Gracefully stop the application
        if 'application' in locals():
            # Cancel the queue worker task before shutting down the application
            queue_task = application.bot_data.get('queue_worker_task')
            if queue_task and not queue_task.done():
                logger.info("Cancelling the queue worker task...")
                queue_task.cancel()
                try:
                    # Wait for the task to acknowledge the cancellation
                    await queue_task
                except asyncio.CancelledError:
                    logger.info("Queue worker task successfully cancelled.")
                except Exception as e:
                    logger.error(f"An error occurred during queue worker shutdown: {e}")

            if application.updater:
                await application.updater.stop()
            await application.stop()
            await application.shutdown()

        logger.info("Bot has been shut down gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
