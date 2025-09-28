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

# Spotify setup
spotify = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=config.SPOTIPY_CLIENT_ID, client_secret=config.SPOTIPY_CLIENT_SECRET
    )
)

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

    logger.info(f"Starting aiohttp health check server on port {port}...")
    # Store runner and site in bot_data to be accessible for cleanup
    application.bot_data['aiohttp_runner'] = runner
    application.bot_data['aiohttp_site'] = site

async def shutdown_health_check_server(application: Application) -> None:
    """Gracefully shuts down the aiohttp web server."""
    runner = application.bot_data.get('aiohttp_runner')
    if runner:
        logger.info("Shutting down aiohttp health check server...")
        await runner.cleanup()


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

async def queue_worker(application: Application):
    """Worker that processes the download queue."""
    while True:
        item = await download_queue.get()
        update, info, message = item['update'], item['info'], item['message']

        try:
            await download_and_send_song(update, application, info, message)
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

    return SELECTING_ACTION

async def set_delay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handles the admin's reply to set the delay."""
    try:
        delay = int(update.message.text)
        if delay < 0:
            await update.message.reply_text("Please provide a non-negative number.", quote=True)
            return SETTING_DELAY

        context.bot_data['auto_delete_delay'] = delay
        await db.set_setting('auto_delete_delay', delay)

        await update.message.reply_text(f"✅ Auto-delete delay set to {delay} minutes." if delay > 0 else "✅ Auto-deletion disabled.", quote=True)
    except (ValueError):
        await update.message.reply_text("Invalid number. Please send a valid number of minutes.", quote=True)
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

# --- Song Handling Logic ---
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
    ydl_opts = {'format': 'bestaudio/best', 'noplaylist': True, 'default_search': 'ytsearch1', 'extract_flat': 'in_playlist'}
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch:{query}", download=False)
            if 'entries' in info and info['entries']: info = info['entries'][0]

            video_id = info['id']
            # Don't cache song info in bot_data anymore. Pass it directly.

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
        keyboard = [[InlineKeyboardButton("Subscribe to Channel", url=f"https://t.me/{config.FORCE_SUB_CHANNEL.replace('@', '')}")]]
        await update.message.reply_text("You must subscribe to our channel to get the song.", reply_markup=InlineKeyboardMarkup(keyboard))

async def download_and_send_song(update: Update, application: Application, info: dict, message):
    chat_id = message.chat_id
    download_path = os.path.join('downloads', str(chat_id))
    os.makedirs(download_path, exist_ok=True)

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
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            await message.edit_text("Downloading...")
            ydl.download([info['webpage_url']])

            downloaded_mp3_path = os.path.join(download_path, f"{base_filename}.mp3")
            for file in os.listdir(download_path):
                if file.startswith(base_filename) and file.split('.')[-1] in ['jpg', 'jpeg', 'png', 'webp']:
                    thumbnail_path = os.path.join(download_path, file)
                    break

            if not os.path.exists(downloaded_mp3_path):
                raise FileNotFoundError(f"Downloaded MP3 not found at {downloaded_mp3_path}")

            if thumbnail_path and os.path.exists(thumbnail_path):
                try:
                    audio = MP3(downloaded_mp3_path, ID3=ID3)
                except ID3NoHeaderError:
                    audio = MP3(downloaded_mp3_path)
                    audio.add_tags()

                mime_type = 'image/jpeg' if thumbnail_path.endswith(('.jpg', '.jpeg')) else 'image/png'
                with open(thumbnail_path, 'rb') as art:
                    audio.tags.add(APIC(encoding=3, mime=mime_type, type=3, desc='Cover', data=art.read()))
                audio.save()
                logger.info(f"Embedded thumbnail into {downloaded_mp3_path}")

            await message.edit_text("Uploading song...")
            title, artist, duration, album = info.get('title', 'Unknown Title'), info.get('uploader', 'Unknown Artist'), info.get('duration', 0), info.get('album', None)
            caption = f"🎵 **{title}**\n👤 **{artist}**" + (f"\n💿 **{album}**" if album else "")
            delay = application.bot_data.get('auto_delete_delay')
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
                    thumbnail=thumbnail_path
                )

            if delay > 0:
                application.job_queue.run_once(delete_message_job, when=timedelta(minutes=delay), data={'message_id': sent_message.message_id}, chat_id=chat_id, name=f"delete_{chat_id}_{sent_message.message_id}")

            await message.delete()

    except Exception as e:
        logger.error(f"Error in download_and_send_song: {e}")
        await message.edit_text("Sorry, an unexpected error occurred during download.")
    finally:
        if downloaded_mp3_path and os.path.exists(downloaded_mp3_path):
            os.remove(downloaded_mp3_path)
        if thumbnail_path and os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)

        if os.path.exists(download_path) and not os.listdir(download_path):
            os.rmdir(download_path)

async def main() -> None:
    """Start the bot and the health check server."""
    await db.initialize_db()
    loaded_settings = await db.load_all_settings()

    # Use post_init and post_shutdown for the health check server
    application = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(start_health_check_server)
        .post_shutdown(shutdown_health_check_server)
        .build()
    )

    application.bot_data.update(loaded_settings)

    # The queue worker should be started as a background task
    # It will be managed by the application's event loop
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

    # run_polling will now also manage the aiohttp server lifecycle
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())