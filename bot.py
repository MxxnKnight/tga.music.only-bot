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
import settings
from datetime import timedelta
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

# Conversation states for Admin Panel
SELECTING_ACTION, SETTING_DELAY, BROADCASTING_MESSAGE, BROADCASTING_CONFIRM = range(4)


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

    # If the command is triggered, send a new panel. If it's from a callback, edit the existing one.
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
    else:
        if 'panel_message_id' in context.user_data:
            try:
                await context.bot.delete_message(update.effective_chat.id, context.user_data['panel_message_id'])
            except Exception:
                pass # Ignore if message is already deleted

        message = await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        context.user_data['panel_message_id'] = message.message_id

    return SELECTING_ACTION

async def admin_panel_actions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles callbacks for navigating the admin panel."""
    query = update.callback_query
    await query.answer()
    data = query.data

    async def save_and_update_panel(panel_function):
        settings.save_settings(context.bot_data)
        text, keyboard = panel_function(context)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

    if data == "admin_back_to_main":
        text, keyboard = admin_panel.get_main_panel(context)
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)
        return SELECTING_ACTION

    elif data == "admin_upload_mode":
        await save_and_update_panel(admin_panel.get_upload_mode_panel)
    elif data.startswith("admin_set_upload_"):
        context.bot_data['upload_mode'] = data.split('_')[-1]
        await save_and_update_panel(admin_panel.get_upload_mode_panel)
    elif data == "admin_queue":
        await save_and_update_panel(admin_panel.get_queue_panel)
    elif data.startswith("admin_set_queue_"):
        context.bot_data['queue_enabled'] = data.split('_')[-1] == 'enabled'
        await save_and_update_panel(admin_panel.get_queue_panel)
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

    return SELECTING_ACTION

async def set_delay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the admin's reply to set the delay."""
    try:
        delay = int(update.message.text)
        if delay < 0:
            await update.message.reply_text("Please provide a non-negative number.", quote=True)
            return SETTING_DELAY

        context.bot_data['auto_delete_delay'] = delay
        settings.save_settings(context.bot_data)

        await update.message.reply_text(f"✅ Auto-delete delay set to {delay} minutes." if delay > 0 else "✅ Auto-deletion disabled.", quote=True)
    except (ValueError):
        await update.message.reply_text("Invalid number. Please send a valid number of minutes.", quote=True)
        return SETTING_DELAY

    await panel_command(update, context)
    return SELECTING_ACTION

async def broadcast_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the message to be broadcasted."""
    context.user_data['broadcast_message'] = update.message

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

    broadcast_message = context.user_data.get('broadcast_message')
    if not broadcast_message:
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
            await context.bot.copy_message(
                chat_id=target_chat_id,
                from_chat_id=broadcast_message.chat_id,
                message_id=broadcast_message.message_id
            )
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

# --- Song Handling Logic (remains unchanged) ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if update.effective_chat.type == 'private': await db.add_user(user_id)
    if str(update.effective_chat.id) != config.ALLOWED_GROUP_ID and update.effective_chat.type != 'private': return
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
    await message.edit_text(f"Searching for '{query}'...")
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'default_search': 'ytsearch1', 'extract_flat': 'in_playlist'}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info and info['entries']: info = info['entries'][0]
            video_id = info['id']
            context.bot_data[video_id] = info
            if context.bot_data.get('upload_mode') == 'direct':
                if await is_user_subscribed(update.effective_user.id, context):
                    if context.bot_data.get('queue_enabled'):
                        await download_queue.put({'update': update, 'info': info, 'message': message})
                        await message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
                    else:
                        await download_and_send_song(update, context, info, message)
                else:
                    keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")], [InlineKeyboardButton("Try Again", callback_data=f"checksub_{video_id}")]]
                    await message.edit_text("You must subscribe to our channel to download songs directly.", reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                title, artist, album = info.get('title', 'Unknown Title'), info.get('uploader', 'Unknown Artist'), info.get('album', None)
                caption = f"🎵 **{title}**\n👤 **{artist}**" + (f"\n💿 **{album}**" if album else "")
                keyboard = [[InlineKeyboardButton("Get Song", url=f"https://t.me/{config.BOT_USERNAME}?start=get_song_{video_id}")]]
                await message.edit_message_text(caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        await message.edit_text("Could not find the song or an error occurred.")

async def checksub_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    video_id = query.data.split("_", 1)[1]
    if await is_user_subscribed(query.from_user.id, context):
        await query.message.edit_text("Thank you for subscribing! Processing request...")
        info = context.bot_data.get(video_id)
        if info:
            if context.bot_data.get('queue_enabled'):
                await download_queue.put({'update': update, 'info': info, 'message': query.message})
                await query.message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
            else:
                await download_and_send_song(update, context, info, query.message)
        else:
            await query.message.edit_text("Sorry, the song request expired.")
    else:
        await query.message.edit_text("You are still not subscribed. Please join the channel and try again.")

async def send_song_in_pm(update: Update, context: ContextTypes.DEFAULT_TYPE, video_id: str):
    await db.add_user(update.effective_user.id)
    info = context.bot_data.get(video_id)
    if not info:
        await update.message.reply_text("This song link has expired or is invalid.")
        return
    if await is_user_subscribed(update.effective_user.id, context):
        message = await update.message.reply_text("Processing your request...")
        if context.bot_data.get('queue_enabled'):
            await download_queue.put({'update': update, 'info': info, 'message': message})
            await message.edit_text(f"Added to queue. There are {download_queue.qsize()} song(s) ahead of you.")
        else:
            await download_and_send_song(update, context, info, message)
    else:
        keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")]]
        await update.message.reply_text("You must subscribe to our channel to get the song.", reply_markup=InlineKeyboardMarkup(keyboard))

async def download_and_send_song(update: Update, context: ContextTypes.DEFAULT_TYPE, info: dict, message):
    chat_id = message.chat_id
    download_path = os.path.join('downloads', str(chat_id))
    os.makedirs(download_path, exist_ok=True)
    outtmpl = os.path.join(download_path, f"{info['id']}.%(ext)s")
    ydl_opts = {'format': 'bestaudio/best', 'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '320'}], 'outtmpl': outtmpl, 'noplaylist': True, 'writethumbnail': True}
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
            title, artist, duration, album = info.get('title', 'Unknown Title'), info.get('uploader', 'Unknown Artist'), info.get('duration', 0), info.get('album', None)
            caption = f"🎵 **{title}**\n👤 **{artist}**" + (f"\n💿 **{album}**" if album else "")
            delay = context.bot_data.get('auto_delete_delay')
            if delay > 0: caption += f"\n\n⚠️ *This file will be deleted in {delay} minutes.*"
            with open(downloaded_file, 'rb') as audio_file:
                sent_message = await context.bot.send_audio(chat_id=chat_id, audio=audio_file, caption=caption, title=title, performer=artist, duration=duration, parse_mode=ParseMode.MARKDOWN)
            if delay > 0:
                context.job_queue.run_once(delete_message_job, when=timedelta(minutes=delay), data={'message_id': sent_message.message_id}, chat_id=chat_id, name=f"delete_{chat_id}_{sent_message.message_id}")
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
    loaded_settings = settings.load_settings()
    application = Application.builder().token(config.BOT_TOKEN).build()
    application.bot_data.update(loaded_settings)
    asyncio.create_task(queue_worker(application))

    admin_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("panel", panel_command)],
        states={
            SELECTING_ACTION: [CallbackQueryHandler(admin_panel_actions)],
            SETTING_DELAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_delay_handler)],
            BROADCASTING_MESSAGE: [MessageHandler(filters.ALL & ~filters.COMMAND, broadcast_message_handler)],
            BROADCASTING_CONFIRM: [CallbackQueryHandler(broadcast_confirmation_handler)]
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

    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())