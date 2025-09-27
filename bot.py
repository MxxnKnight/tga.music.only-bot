# bot.py
import logging
import config
import os
import re
import yt_dlp
import spotipy
import asyncio
import db
from spotipy.oauth2 import SpotifyClientCredentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler, ConversationHandler

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Spotify setup
spotify = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=config.SPOTIPY_CLIENT_ID, client_secret=config.SPOTIPY_CLIENT_SECRET
    )
)

# Conversation states for broadcast
BROADCAST_MESSAGE, BROADCAST_CONFIRM = range(2)

# --- Queue System ---
download_queue = asyncio.Queue()

async def queue_worker(context: ContextTypes.DEFAULT_TYPE):
    """Worker that processes the download queue."""
    while True:
        item = await download_queue.get()
        update, info, message = item['update'], item['info'], item['message']

        try:
            await download_and_send_song(update, context, info, message)
        except Exception as e:
            logger.error(f"Error processing item from queue: {e}")
            await message.edit_text("Sorry, an error occurred while processing your request from the queue.")
        finally:
            download_queue.task_done()

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

# --- Command Handlers ---

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

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gets the total number of users from the database."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    user_count = await db.get_users_count()
    await update.message.reply_text(f"Total users in the database: {user_count}")

async def toggle_queue_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command to toggle the download queue."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    current_status = context.bot_data.get('queue_enabled', config.QUEUE_ENABLED)
    new_status = not current_status
    context.bot_data['queue_enabled'] = new_status

    await update.message.reply_text(f"Queue system has been {'enabled' if new_status else 'disabled'}.")

async def upload_mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command to change the upload mode."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    current_mode = context.bot_data.get('upload_mode', config.UPLOAD_MODE)
    new_mode = 'info' if current_mode == 'direct' else 'direct'
    context.bot_data['upload_mode'] = new_mode
    await update.message.reply_text(f"Upload mode has been switched to '{new_mode}'.")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the broadcast conversation."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("You are not authorized to use this command.")
        return ConversationHandler.END

    await update.message.reply_text("Please reply to the message you want to broadcast.")
    return BROADCAST_MESSAGE

async def broadcast_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the message to be broadcasted and asks for confirmation."""
    message_to_broadcast = update.message.reply_to_message
    if not message_to_broadcast:
        await update.message.reply_text("Please reply to a message to broadcast it. Cancelling.")
        return ConversationHandler.END

    context.user_data['broadcast_message_id'] = message_to_broadcast.message_id
    context.user_data['broadcast_chat_id'] = message_to_broadcast.chat_id

    keyboard = [
        [InlineKeyboardButton("To All Users", callback_data="broadcast_users")],
        [InlineKeyboardButton("To Group", callback_data="broadcast_group")],
        [InlineKeyboardButton("Cancel", callback_data="broadcast_cancel")]
    ]
    await update.message.reply_text(
        "Where do you want to broadcast this message?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return BROADCAST_CONFIRM

async def broadcast_confirmation_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the broadcast confirmation and sends the message."""
    query = update.callback_query
    await query.answer()

    broadcast_type = query.data
    if broadcast_type == 'broadcast_cancel':
        await query.edit_message_text("Broadcast cancelled.")
        return ConversationHandler.END

    message_id = context.user_data.get('broadcast_message_id')
    chat_id = context.user_data.get('broadcast_chat_id')
    if not message_id or not chat_id:
        await query.edit_message_text("Error: Could not find the message to broadcast. Please start again.")
        return ConversationHandler.END

    await query.edit_message_text("Starting broadcast...")

    target_chats = []
    if broadcast_type == 'broadcast_users':
        target_chats = await db.get_all_users()
    elif broadcast_type == 'broadcast_group':
        target_chats = [config.ALLOWED_GROUP_ID]

    success_count = 0
    fail_count = 0
    for target_chat_id in target_chats:
        try:
            await context.bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=chat_id,
                message_id=message_id
            )
            success_count += 1
            await asyncio.sleep(0.1)
        except Exception as e:
            fail_count += 1
            logger.error(f"Failed to send broadcast to {target_chat_id}: {e}")

    await query.edit_message_text(f"Broadcast complete.\n- Sent: {success_count}\n- Failed: {fail_count}")
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the broadcast conversation."""
    await update.message.reply_text("Broadcast cancelled.")
    return ConversationHandler.END

# --- Song Handling Logic ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user messages for song requests."""
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private':
        await db.add_user(user_id)

    if str(update.effective_chat.id) != config.ALLOWED_GROUP_ID and update.effective_chat.type != 'private':
        await update.message.reply_text("This group is not authorized to use this bot.")
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
            try:
                track = spotify.track(message_text)
                query = f"{track['name']} {track['artists'][0]['name']}"
                await message.edit_text(f"Found on Spotify: '{query}'. Now searching on YouTube...")
            except Exception as e:
                logger.error(f"Spotify error: {e}")
                await message.edit_text("Could not process the Spotify link.")
                return
        elif "jiosaavn.com" in message_text:
            song_name_match = re.search(r'/song/[^/]+/([^/?]+)', message_text)
            if song_name_match:
                query = song_name_match.group(1).replace('-', ' ')
                await message.edit_text(f"Found on Saavn: '{query}'. Now searching on YouTube...")
            else:
                await message.edit_text("Could not extract info from Saavn link.")
                return

    await process_song_request(update, context, query, message)

async def process_song_request(update: Update, context: ContextTypes.DEFAULT_TYPE, query: str, message):
    """Find song info and then handle based on upload mode and queue status."""
    await message.edit_text(f"Searching for '{query}'...")

    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'default_search': 'ytsearch1', 'extract_flat': 'in_playlist'}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info and info['entries']:
                info = info['entries'][0]

            video_id = info['id']
            context.bot_data[video_id] = info

            upload_mode = context.bot_data.get('upload_mode', config.UPLOAD_MODE)

            if upload_mode == 'direct':
                subscribed = await is_user_subscribed(update.effective_user.id, context)
                if subscribed:
                    queue_enabled = context.bot_data.get('queue_enabled', config.QUEUE_ENABLED)
                    if queue_enabled:
                        await download_queue.put({'update': update, 'info': info, 'message': message})
                        await message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
                    else:
                        await download_and_send_song(update, context, info, message)
                else:
                    keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")],
                                [InlineKeyboardButton("Try Again", callback_data=f"checksub_{video_id}")]]
                    await message.edit_text("You must subscribe to our channel to download songs directly.", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                title = info.get('title', 'Unknown Title')
                artist = info.get('uploader', 'Unknown Artist')
                album = info.get('album', None)
                caption = f"🎵 **{title}**\n👤 **{artist}**"
                if album:
                    caption += f"\n💿 **{album}**"
                keyboard = [[InlineKeyboardButton("Get Song", url=f"https://t.me/{config.BOT_USERNAME}?start=get_song_{video_id}")]]
                await message.edit_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)

    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await message.edit_text("Could not find the song or an error occurred.")

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses."""
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("checksub_"):
        video_id = data.split("_", 1)[1]
        subscribed = await is_user_subscribed(query.from_user.id, context)
        if subscribed:
            await query.message.edit_text("Thank you for subscribing! Processing request...")
            info = context.bot_data.get(video_id)
            if info:
                queue_enabled = context.bot_data.get('queue_enabled', config.QUEUE_ENABLED)
                if queue_enabled:
                    await download_queue.put({'update': update, 'info': info, 'message': query.message})
                    await query.message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
                else:
                    await download_and_send_song(update, context, info, query.message)
            else:
                await query.message.edit_text("Sorry, the song request expired.")
        else:
            await query.message.edit_text("You are still not subscribed. Please join the channel and try again.")

async def send_song_in_pm(update: Update, context: ContextTypes.DEFAULT_TYPE, video_id: str):
    """Send the song to the user in PM after checking subscription."""
    await db.add_user(update.effective_user.id)
    info = context.bot_data.get(video_id)
    if not info:
        await update.message.reply_text("This song link has expired or is invalid.")
        return

    subscribed = await is_user_subscribed(update.effective_user.id, context)
    if subscribed:
        message = await update.message.reply_text("Processing your request...")
        queue_enabled = context.bot_data.get('queue_enabled', config.QUEUE_ENABLED)
        if queue_enabled:
            await download_queue.put({'update': update, 'info': info, 'message': message})
            await message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
        else:
            await download_and_send_song(update, context, info, message)
    else:
        keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")]]
        await update.message.reply_text("You must subscribe to our channel to get the song.", reply_markup=InlineKeyboardMarkup(keyboard))

async def download_and_send_song(update: Update, context: ContextTypes.DEFAULT_TYPE, info: dict, message):
    """Downloads a song using yt-dlp and sends it to the user."""
    chat_id = message.chat_id
    download_path = os.path.join('downloads', str(chat_id))
    os.makedirs(download_path, exist_ok=True)

    outtmpl = os.path.join(download_path, f"{info['id']}.%(ext)s")

    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}],
        'outtmpl': outtmpl, 'noplaylist': True,
        'writethumbnail': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await message.edit_text("Downloading...")
            ydl.download([info['webpage_url']])

            downloaded_file = outtmpl.replace('.%(ext)s', '.mp3')
            if not os.path.exists(downloaded_file):
                for file in os.listdir(download_path):
                    if file.startswith(info['id']) and file.endswith('.mp3'):
                        downloaded_file = os.path.join(download_path, file)
                        break
            if not os.path.exists(downloaded_file): raise FileNotFoundError("Downloaded MP3 not found.")

            await message.edit_text("Uploading song...")

            title = info.get('title', 'Unknown Title')
            artist = info.get('uploader', 'Unknown Artist')
            duration = info.get('duration', 0)
            album = info.get('album', None)

            caption = f"🎵 **{title}**\n👤 **{artist}**"
            if album:
                caption += f"\n💿 **{album}**"

            with open(downloaded_file, 'rb') as audio_file:
                await context.bot.send_audio(
                    chat_id=chat_id, audio=audio_file, caption=caption,
                    title=title, performer=artist, duration=duration, parse_mode=ParseMode.MARKDOWN
                )

            os.remove(downloaded_file)
            await message.delete()

    except Exception as e:
        logger.error(f"Error in download_and_send_song: {e}")
        await message.edit_text("Sorry, an unexpected error occurred during download.")
    finally:
        if os.path.exists(download_path):
            if os.listdir(download_path):
                for file in os.listdir(download_path): os.remove(os.path.join(download_path, file))
            os.rmdir(download_path)

async def main() -> None:
    """Start the bot."""
    await db.initialize_db()

    application = Application.builder().token(config.BOT_TOKEN).build()

    application.bot_data.setdefault('upload_mode', config.UPLOAD_MODE)
    application.bot_data.setdefault('queue_enabled', config.QUEUE_ENABLED)

    # Start the queue worker
    asyncio.create_task(queue_worker(application))

    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_command)],
        states={
            BROADCAST_MESSAGE: [MessageHandler(filters.REPLY, broadcast_message_handler)],
            BROADCAST_CONFIRM: [CallbackQueryHandler(broadcast_confirmation_handler, pattern='^broadcast_.*')]
        },
        fallbacks=[CommandHandler("cancel", cancel_broadcast)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("uploadmode", upload_mode_command))
    application.add_handler(CommandHandler("togglequeue", toggle_queue_command))
    application.add_handler(broadcast_handler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(callback_query_handler, pattern='^checksub_.*'))

    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())