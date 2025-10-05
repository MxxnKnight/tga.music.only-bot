# db.py
import logging
import motor.motor_asyncio
from config import MONGODB_URI, UPLOAD_MODE, QUEUE_ENABLED, AUTO_DELETE_DELAY

# Enable logging
logger = logging.getLogger(__name__)

# --- MongoDB Client Setup ---
# It's recommended to have a single client instance per application
client = None
db = None
users_collection = None
settings_collection = None
file_cache_collection = None

async def initialize_db():
    """
    Initializes the MongoDB connection, gets the database and collections,
    and ensures necessary indexes are created.
    """
    global client, db, users_collection, settings_collection, file_cache_collection

    if not MONGODB_URI:
        raise ValueError("FATAL: MONGODB_URI environment variable is not set.")

    try:
        # Create a single, shared client instance
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)

        # Explicitly get the database by name.
        db = client["music_bot"]

        users_collection = db["users"]
        settings_collection = db["settings"]
        file_cache_collection = db["file_cache"]

        # --- Create Indexes ---
        # Create a unique index on user_id to prevent duplicate users
        await users_collection.create_index("user_id", unique=True)
        # Create a unique index on the setting key to prevent duplicate settings
        await settings_collection.create_index("key", unique=True)
        # Create a unique index on the video_id for fast cache lookups
        await file_cache_collection.create_index("video_id", unique=True)

        # --- Seed Default Settings ---
        # This ensures that on the first run, the bot has the necessary settings.
        # Using $setOnInsert makes this operation idempotent.
        default_settings = {
            'upload_mode': UPLOAD_MODE,
            'queue_enabled': QUEUE_ENABLED,
            'auto_delete_delay': AUTO_DELETE_DELAY,
        }
        for key, value in default_settings.items():
            await settings_collection.update_one(
                {'key': key},
                {'$setOnInsert': {'key': key, 'value': value}},
                upsert=True
            )

        logger.info("MongoDB connection established, collections/indexes are ready, and default settings are seeded.")

    except Exception as e:
        logger.error(f"Failed to initialize MongoDB connection: {e}", exc_info=True)
        raise

async def add_user(user_id: int):
    """
    Adds a new user to the database if they don't already exist.
    This is an idempotent operation.
    """
    if users_collection is None:
        logger.error("Database not initialized. Call initialize_db() first.")
        return
    try:
        # Use update_one with upsert=True to insert if not exists, or do nothing if it does.
        await users_collection.update_one(
            {'user_id': user_id},
            {'$setOnInsert': {'user_id': user_id}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Failed to add user {user_id}: {e}", exc_info=True)

async def get_all_users() -> list[int]:
    """
    Retrieves a list of all user IDs from the database.
    """
    if users_collection is None:
        logger.error("Database not initialized. Call initialize_db() first.")
        return []
    try:
        cursor = users_collection.find({}, {'_id': 0, 'user_id': 1})
        return [doc['user_id'] async for doc in cursor]
    except Exception as e:
        logger.error(f"Failed to get all users: {e}", exc_info=True)
        return []

async def get_users_count() -> int:
    """
    Returns the total number of users in the database.
    """
    if users_collection is None:
        logger.error("Database not initialized. Call initialize_db() first.")
        return 0
    try:
        return await users_collection.count_documents({})
    except Exception as e:
        logger.error(f"Failed to get user count: {e}", exc_info=True)
        return 0

async def set_setting(key: str, value):
    """
    Sets a new value for a given setting or creates it if it doesn't exist.
    """
    if settings_collection is None:
        logger.error("Database not initialized. Call initialize_db() first.")
        return
    try:
        await settings_collection.update_one(
            {'key': key},
            {'$set': {'value': value}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Failed to set setting '{key}': {e}", exc_info=True)

async def load_all_settings() -> dict:
    """
    Loads all settings from the database into a dictionary.
    """
    if settings_collection is None:
        logger.error("Database not initialized. Call initialize_db() first.")
        return {}
    settings = {}
    try:
        cursor = settings_collection.find({})
        async for doc in cursor:
            settings[doc['key']] = doc['value']
        logger.info(f"Loaded settings from DB: {settings}")
        return settings
    except Exception as e:
        logger.error(f"Failed to load settings: {e}", exc_info=True)
        return {}

async def add_to_cache(video_id: str, file_id: str):
    """
    Saves a video's file_id to the cache for future use.
    """
    if not file_cache_collection:
        logger.error("Database not initialized. Call initialize_db() first.")
        return
    try:
        await file_cache_collection.update_one(
            {'video_id': video_id},
            {'$set': {'file_id': file_id}},
            upsert=True
        )
    except Exception as e:
        logger.error(f"Failed to cache file_id for video {video_id}: {e}", exc_info=True)

async def get_from_cache(video_id: str) -> str | None:
    """
    Retrieves a cached file_id for a given video_id.
    Returns the file_id if found, otherwise None.
    """
    if not file_cache_collection:
        logger.error("Database not initialized. Call initialize_db() first.")
        return None
    try:
        doc = await file_cache_collection.find_one({'video_id': video_id})
        return doc.get('file_id') if doc else None
    except Exception as e:
        logger.error(f"Failed to get file_id from cache for video {video_id}: {e}", exc_info=True)
        return None