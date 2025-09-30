# db.py
# db.py
import asyncpg
import config
import logging
import json
import datetime

logger = logging.getLogger(__name__)
pool = None

DEFAULT_SETTINGS = {
    "upload_mode": config.UPLOAD_MODE,
    "queue_enabled": config.QUEUE_ENABLED,
    "auto_delete_delay": config.AUTO_DELETE_DELAY,
}

import os

async def initialize_db():
    """
    Initializes the database connection pool and creates tables if they don't exist.
    Also ensures default settings are in the database.
    """
    global pool
    database_url = os.environ.get('DATABASE_URL') or config.DATABASE_URL

    if not database_url:
        logger.error("DATABASE_URL not set. Database features will be disabled.")
        return
    try:
        pool = await asyncpg.create_pool(dsn=database_url)
        async with pool.acquire() as connection:
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value JSONB
                );
            ''')
            # Ensure default settings are present
            for key, value in DEFAULT_SETTINGS.items():
                await connection.execute(
                    "INSERT INTO settings (key, value) VALUES ($1, $2) ON CONFLICT (key) DO NOTHING",
                    key, json.dumps(value)
                )
        logger.info("Database connection pool established and tables initialized.")
    except Exception as e:
        logger.critical(f"Could not connect to PostgreSQL database: {e}")
        pool = None

async def add_user(user_id: int):
    """Adds a new user to the database if they don't already exist."""
    if not pool: return
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING", user_id)
    except Exception as e:
        logger.error(f"Error adding user {user_id} to database: {e}")

async def get_all_users() -> list[int]:
    """Retrieves a list of all user IDs from the database."""
    if not pool: return []
    try:
        async with pool.acquire() as conn:
            records = await conn.fetch("SELECT user_id FROM users")
            return [record['user_id'] for record in records]
    except Exception as e:
        logger.error(f"Error getting all users from database: {e}")
        return []

async def get_users_count() -> int:
    """Retrieves the total number of users from the database."""
    if not pool: return 0
    try:
        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM users")
            return count or 0
    except Exception as e:
        logger.error(f"Error getting user count from database: {e}")
        return 0

async def load_all_settings() -> dict:
    """Loads all settings from the database."""
    if not pool: return DEFAULT_SETTINGS.copy()
    try:
        async with pool.acquire() as conn:
            records = await conn.fetch("SELECT key, value FROM settings")
            settings = {record['key']: record['value'] for record in records}
            # Ensure all default keys are present in the loaded settings
            for key, value in DEFAULT_SETTINGS.items():
                settings.setdefault(key, value)
            return settings
    except Exception as e:
        logger.error(f"Error loading settings from database: {e}")
        return DEFAULT_SETTINGS.copy()

async def set_setting(key: str, value):
    """Saves a specific setting to the database."""
    if not pool: return
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO settings (key, value) VALUES ($1, $2)
                ON CONFLICT (key) DO UPDATE SET value = $2
                """,
                key, json.dumps(value)
            )
    except Exception as e:
        logger.error(f"Error setting '{key}' in database: {e}")

