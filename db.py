# db.py
import asyncpg
import config
import logging

logger = logging.getLogger(__name__)
pool = None

async def initialize_db():
    """
    Initializes the database connection pool and creates the users table if it doesn't exist.
    """
    global pool
    if not config.DATABASE_URL:
        logger.error("DATABASE_URL not set in config.py. Database features will be disabled.")
        return
    try:
        pool = await asyncpg.create_pool(config.DATABASE_URL)
        async with pool.acquire() as connection:
            await connection.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY
                )
            ''')
        logger.info("Database connection pool established and table initialized.")
    except Exception as e:
        logger.critical(f"Could not connect to PostgreSQL database: {e}")
        pool = None

async def add_user(user_id: int):
    """
    Adds a new user to the database if they don't already exist.
    """
    if not pool:
        return
    try:
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO users (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
                user_id
            )
    except Exception as e:
        logger.error(f"Error adding user {user_id} to database: {e}")

async def get_all_users() -> list[int]:
    """
    Retrieves a list of all user IDs from the database.
    """
    if not pool:
        return []
    try:
        async with pool.acquire() as connection:
            records = await connection.fetch("SELECT user_id FROM users")
            return [record['user_id'] for record in records]
    except Exception as e:
        logger.error(f"Error getting all users from database: {e}")
        return []

async def get_users_count() -> int:
    """
    Retrieves the total number of users from the database.
    """
    if not pool:
        return 0
    try:
        async with pool.acquire() as connection:
            count = await connection.fetchval("SELECT COUNT(*) FROM users")
            return count or 0
    except Exception as e:
        logger.error(f"Error getting user count from database: {e}")
        return 0