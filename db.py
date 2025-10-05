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

async def initialize_db():
    """
    Initializes the MongoDB connection, gets the database and collections,
    and ensures necessary indexes are created.
    """
    global client, db, users_collection, settings_collection

    if not MONGODB_URI:
        raise ValueError("FATAL: MONGODB_URI environment variable is not set.")

    try:
        # Create a single, shared client instance
        client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)

        # The database name can be specified in the URI, or you can get it like this.
        # Render's connection string includes the database name.
        db = client.get_default_database()
        if not db:
            # Fallback if the database name is not in the URI
            db = client["music_bot"]

        users_collection = db["users"]
        settings_collection = db["settings"]

        # --- Create Indexes ---
        # Create a unique index on user_id to prevent duplicate users
        await users_collection.create_index("user_id", unique=True)
        # Create a unique index on the setting key to prevent duplicate settings
        await settings_collection.create_index("key", unique=True)

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
    if not users_collection:
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
    if not users_collection:
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
    if not users_collection:
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
    if not settings_collection:
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
    if not settings_collection:
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