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
import functools
import datetime
from datetime import timedelta
from spotipy.oauth2 import SpotifyClientCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from aiohttp import web
from mutagen.mp3 import MP3
from mutagen.id3 import APIC, ID3NoHeaderError, ID3

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

# --- Health Check Server (aiohttp) ---
async def health_check_handler(request: web.Request) -> web.Response:
    """AIOHTTP handler for the health check endpoint."""
    return web.Response(text="OK")

async def start_health_check_server(application: Application) -> None:
    """Starts the aiohttp web server for health checks."""
    port = int(os.environ.get('PORT', 8080))
    app = web.Application()
    app.add_routes([web.get('/healthz', health_check_handler)])

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host='0.0.0.0', port=port)
    await site.start()

    logger.info(f"Health check server running on port {port}")
    # Store runner and site in bot_data to be accessible for cleanup
    application.bot_data['aiohttp_runner'] = runner
    application.bot_data['aiohttp_site'] = site

async def shutdown_health_check_server(application: Application) -> None:
    """Gracefully shuts down the aiohttp web server."""
    runner = application.bot_data.get('aiohttp_runner')
    if runner:
        logger.info("Shutting down health check server...")
        await runner.cleanup()


# Conversation states for Admin Panel
SELECTING_ACTION, SETTING_DELAY, BROADCASTING_MESSAGE, BROADCASTING_CONFIRM, UPDATING_COOKIES = range(5)

COOKIE_FILE = os.path.join(os.getcwd(), "cookies.txt")

# --- Cookie Utilities ---
def parse_cookie_file(cookie_data: str) -> datetime.datetime | None:
    """Parses a Netscape cookie file string to find the latest expiration date."""
    latest_expiry = 0
    for line in cookie_data.strip().split('\n'):
        if line.startswith('#') or not line.strip():
            continue
        parts = line.split('\t')
        if len(parts) >= 5:
            try:
                expiry_timestamp = int(parts[4])
                if expiry_timestamp > latest_expiry:
                    latest_expiry = expiry_timestamp
            except (ValueError, IndexError):
                continue

    if latest_expiry > 0:
        return datetime.datetime.fromtimestamp(latest_expiry, tz=datetime.timezone.utc)
    return None

async def write_cookies_to_file(cookie_data: str | None):
    """Writes the provided cookie data to the COOKIE_FILE."""
    try:
        if cookie_data:
            with open(COOKIE_FILE, "w") as f:
                f.write(cookie_data)
            logger.info(f"Successfully wrote cookies to {COOKIE_FILE}")
        else:
            if os.path.exists(COOKIE_FILE):
                os.remove(COOKIE_FILE)
            logger.info(f"Removed {COOKIE_FILE} as cookie data is empty.")
    except Exception as e:
        logger.error(f"Failed to write to {COOKIE_FILE}: {e}")

# --- Job Queue Callbacks ---
async def delete_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Deletes a message specified in the job context."""
    job = context.job
    try:
        await context.bot.delete_message(chat_id=job.chat_id, message_id=job.data['message_id'])
        logger.info(f"Auto-deleted message {job.data['message_id']} in chat {job.chat_id}")
    except Exception as e:
        logger.error(f"Failed to delete message {job.data['message_id']} in chat {job.chat_id}: {e}")

async def check_cookie_expiration_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Checks daily if cookies are about to expire and notifies admins."""
    expires_at = context.bot_data.get('cookie_expires_at')
    if not expires_at:
        return

    # Ensure expires_at is timezone-aware for comparison
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=datetime.timezone.utc)

    now = datetime.datetime.now(datetime.timezone.utc)
    days_left = (expires_at - now).days

    # Notify if expiring within 7 days, or if already expired
    if days_left <= 7:
        logger.info(f"YouTube cookies are expiring in {days_left} days. Notifying admins.")
        if days_left > 0:
            message = f"⚠️ **Cookie Expiration Warning** ⚠️\n\nYour YouTube cookies will expire in *{days_left} day(s)*.\n\nPlease update them soon via the admin panel to avoid download interruptions."
        else:
            message = f"🚨 **Cookies Expired** 🚨\n\nYour YouTube cookies have expired. Downloads may fail until they are updated via the admin panel."

        for admin_id in config.ADMINS:
            try:
                await context.bot.send_message(chat_id=int(admin_id), text=message, parse_mode=ParseMode.MARKDOWN)
            except Exception as e:
                logger.error(f"Failed to send expiration warning to admin {admin_id}: {e}")


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
                logger.error(f"Error processing item from queue: {e}")
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
            logger.error(f"Unexpected error in queue worker: {e}")

async def start_queue_worker(application: Application) -> None:
    """Starts the queue worker as a background task."""
    task = asyncio.create_task(queue_worker(application))
    application.bot_data['queue_worker_task'] = task

# --- Admin and Helper Functions ---
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
            await update.message.reply_text("Hi! I'm a music bot. Add me to the allowed group to start downloading music.")
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
        await context.bot.answer_callback_query(query.id, text=f"📊 Total users in database: {user_count}", show_alert=True)
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
    elif data == "admin_cookies":
        await update_and_show_panel(admin_panel.get_cookies_panel)
    elif data == "admin_update_cookies":
        await query.edit_message_text("Please send your `cookies.txt` file or paste the cookie data as text.")
        return UPDATING_COOKIES
    elif data == "admin_remove_cookies":
        context.bot_data['cookie_data'] = None
        context.bot_data['cookie_expires_at'] = None
        await db.delete_cookies()
        await write_cookies_to_file(None)
        await context.bot.answer_callback_query(query.id, text="✅ Cookies have been removed.", show_alert=True)
        await update_and_show_panel(admin_panel.get_cookies_panel)


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

async def update_cookies_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles receiving a new cookie file or text, with improved error handling."""
    cookie_data = ""
    try:
        if update.message.document:
            # The ConversationHandler filter already ensures this is a .txt file.
            file = await context.bot.get_file(update.message.document.file_id)
            byte_data = await file.download_as_bytearray()
            cookie_data = byte_data.decode('utf-8')
            if not cookie_data.strip():
                await update.message.reply_text("The provided file appears to be empty. Please try again.")
                return UPDATING_COOKIES
        elif update.message.text:
            cookie_data = update.message.text
            if not cookie_data.strip():
                await update.message.reply_text("The provided text message is empty. Please try again.")
                return UPDATING_COOKIES
    except Exception as e:
        logger.error(f"Error reading cookie data from user: {e}")
        await update.message.reply_text("Sorry, I was unable to read the provided cookie data. Please try again.")
        return UPDATING_COOKIES

    expires_at = parse_cookie_file(cookie_data)
    if not expires_at:
        await update.message.reply_text(
            "⚠️ **Warning**: Could not find a valid expiration date in the cookies. Please ensure they are in the Netscape format. "
            "I will still save them, but automatic expiration warnings may not work correctly.",
            parse_mode=ParseMode.MARKDOWN
        )
        # Default to 1 year from now if no date is found, so we don't spam the user.
        expires_at = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=365)

    # Update db and bot_data
    await db.set_cookies(cookie_data, expires_at)
    context.bot_data['cookie_data'] = cookie_data
    context.bot_data['cookie_expires_at'] = expires_at

    # Write to file for yt-dlp to use
    await write_cookies_to_file(cookie_data)

    await update.message.reply_text("✅ Cookies updated successfully!")

    # Return to the cookies panel
    text, keyboard = admin_panel.get_cookies_panel(context)
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
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'default_search': 'ytsearch1'}
    try:
        # Distinguish between a URL and a search query
        url_pattern = re.compile(r'https?://\S+')
        search_query = query if url_pattern.match(query) else f"ytsearch:{query}"

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(search_query, download=False)
            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            video_id = info['id']

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
        ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True}
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

        ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_id, download=False)

            if context.bot_data.get('queue_enabled'):
                await download_queue.put({'update': update, 'info': info, 'message': message})
                await message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
            else:
                await download_and_send_song(update, context.application, info, message)
        except Exception as e:
            logger.error(f"Error fetching info for PM song: {e}")
            await message.edit_text("Sorry, the song request expired or failed.")
    else:
        if config.FORCE_SUB_CHANNEL:
            keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")]]
            await update.message.reply_text("You must subscribe to our channel to get the song.", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text("Force subscription is not configured.")

def _blocking_download_and_process(ydl_opts, info, download_path, base_filename):
    """
    Handles the blocking I/O tasks: downloading, processing, and embedding thumbnail, with enhanced logging.
    This function is designed to be run in a separate thread.
    """
    os.makedirs(download_path, exist_ok=True)

    # Add cookie file to options if it exists
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE
        logger.info(f"Using cookie file at: {COOKIE_FILE}")
    elif config.COOKIE_FILE_PATH and os.path.exists(config.COOKIE_FILE_PATH):
        # Fallback to env var for backward compatibility
        ydl_opts['cookiefile'] = config.COOKIE_FILE_PATH
        logger.info(f"Using cookie file from env var at: {config.COOKIE_FILE_PATH}")
    else:
        logger.info("No cookie file found or configured.")

    logger.info(f"Starting download with yt-dlp options: {ydl_opts}")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([info['webpage_url']])
        logger.info("yt-dlp download completed successfully.")
    except yt_dlp.utils.DownloadError as e:
        # Log the specific yt-dlp error and re-raise it
        logger.error(f"yt-dlp failed with a DownloadError: {e}")
        raise e # Re-raise the exception to be caught by the calling async function


    downloaded_mp3_path = os.path.join(download_path, f"{base_filename}.mp3")
    thumbnail_path = None
    for file in os.listdir(download_path):
        if file.startswith(base_filename) and file.split('.')[-1] in ['jpg', 'jpeg', 'png', 'webp']:
            thumbnail_path = os.path.join(download_path, file)
            break

    if not os.path.exists(downloaded_mp3_path):
        raise FileNotFoundError(f"Downloaded MP3 not found at {downloaded_mp3_path}")

    thumbnail_bytes = None
    if thumbnail_path and os.path.exists(thumbnail_path):
        try:
            audio = MP3(downloaded_mp3_path, ID3=ID3)
        except ID3NoHeaderError:
            audio = MP3(downloaded_mp3_path)
            audio.add_tags()

        mime_type = 'image/jpeg' if thumbnail_path.endswith(('.jpg', '.jpeg')) else 'image/png'
        with open(thumbnail_path, 'rb') as art:
            thumbnail_bytes = art.read()
            audio.tags.add(APIC(encoding=3, mime=mime_type, type=3, desc='Cover', data=thumbnail_bytes))
        audio.save()
        logger.info(f"Embedded thumbnail into {downloaded_mp3_path}")

    return downloaded_mp3_path, thumbnail_path, thumbnail_bytes

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
                # Only remove directory if it's empty
                if not os.listdir(path):
                    os.rmdir(path)
        except Exception as e:
            logger.error(f"Error during cleanup of {path}: {e}")


async def download_and_send_song(update: Update, application: Application, info: dict, message):
    loop = asyncio.get_running_loop()
    chat_id = message.chat_id
    download_path = os.path.join('downloads', str(chat_id))

    base_filename = info['id']
    outtmpl = os.path.join(download_path, f"{base_filename}.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320'
        }],
        'outtmpl': outtmpl,
        'noplaylist': True,
        'writethumbnail': True
    }

    downloaded_mp3_path = None
    thumbnail_path = None

    try:
        await message.edit_text("Downloading...")

        # Run the blocking download and processing in a separate thread
        blocking_task = functools.partial(_blocking_download_and_process, ydl_opts, info, download_path, base_filename)
        downloaded_mp3_path, thumbnail_path, thumbnail_bytes = await loop.run_in_executor(None, blocking_task)

        await message.edit_text("Uploading song...")
        title, artist, duration, album = info.get('title', 'Unknown Title'), info.get('uploader', 'Unknown Artist'), info.get('duration', 0), info.get('album', None)
        caption = f"🎵 **{title}**\n👤 **{artist}**" + (f"\n💿 **{album}**" if album else "")
        delay = application.bot_data.get('auto_delete_delay', 0)
        if delay > 0:
            caption += f"\n\n⚠️ *This file will be deleted in {delay} minutes.*"

        with open(downloaded_mp3_path, 'rb') as audio_file:
            sent_message = await application.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                caption=caption,
                title=title,
                performer=artist,
                duration=duration,
                parse_mode=ParseMode.MARKDOWN,
                thumbnail=thumbnail_bytes
            )

        if delay > 0:
            application.job_queue.run_once(delete_message_job, when=timedelta(minutes=delay), data={'message_id': sent_message.message_id}, chat_id=chat_id, name=f"delete_{chat_id}_{sent_message.message_id}")

        await message.delete()

    except Exception as e:
        # Log the full traceback for detailed diagnostics
        logger.error("An error occurred in download_and_send_song", exc_info=True)

        # Check for cookie-related errors
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
                await message.edit_text(f"Sorry, an unexpected error occurred during download. The error was: `{e}`")
            except:
                pass
    finally:
        # Run cleanup in a separate thread
        paths_to_clean = [downloaded_mp3_path, thumbnail_path, download_path]
        cleanup_task = functools.partial(_blocking_cleanup, paths_to_clean)
        await loop.run_in_executor(None, cleanup_task)

async def load_cookies_on_start(application: Application) -> None:
    """Loads cookies from the database into bot_data and writes them to a file on startup."""
    logger.info("Loading cookies from database on startup...")
    cookie_data, expires_at = await db.get_cookies()
    if cookie_data and expires_at:
        application.bot_data['cookie_data'] = cookie_data
        application.bot_data['cookie_expires_at'] = expires_at
        await write_cookies_to_file(cookie_data)
        logger.info("Successfully loaded and wrote cookies from database.")
    else:
        logger.info("No cookies found in database.")
        application.bot_data['cookie_data'] = None
        application.bot_data['cookie_expires_at'] = None
        await write_cookies_to_file(None) # Ensure no old file is lingering

async def main() -> None:
    """Initializes, configures, and runs the bot."""
    logger.info("Starting bot initialization...")
    
    # --- Initialization ---
    await db.initialize_db()


    try:
        loaded_settings = await db.load_all_settings()
        logger.info(f"Loaded settings: {loaded_settings}")

        # --- Application Setup ---
        application = (
            Application.builder()
            .token(config.BOT_TOKEN)
            .post_init(start_health_check_server)
            .post_init(start_queue_worker)
            .post_init(load_cookies_on_start)
            .post_shutdown(shutdown_health_check_server)
            .build()
        )

        # Load the persistent settings into the bot
        application.bot_data.update(loaded_settings)

        # --- Command and Message Handlers ---
        admin_conv_handler = ConversationHandler(
            entry_points=[CommandHandler("panel", panel_command)],
            states={
                SELECTING_ACTION: [CallbackQueryHandler(admin_panel_actions)],
                SETTING_DELAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_delay_handler)],
                BROADCASTING_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_message_handler)],
                BROADCASTING_CONFIRM: [CallbackQueryHandler(broadcast_confirmation_handler)],
                UPDATING_COOKIES: [MessageHandler(filters.TEXT | filters.Document.FileExtension("txt"), update_cookies_handler)]
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

        # --- Schedule recurring jobs ---
        application.job_queue.run_daily(check_cookie_expiration_job, time=datetime.time(hour=12, minute=0, tzinfo=datetime.timezone.utc), name="cookie_check")
        logger.info("Scheduled daily cookie expiration check.")

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
        if 'application' in locals() and application.updater:
            await application.updater.stop()
            await application.stop()
            await application.shutdown()

        logger.info("Bot has been shut down gracefully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
