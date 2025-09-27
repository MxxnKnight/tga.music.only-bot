# Telegram Music Bot

This is a powerful Telegram bot for downloading music from various sources, designed to work exclusively within a specified group. It includes features like link detection, force subscription, multiple upload modes, a broadcast system, a queue to manage high traffic, and auto-deletion of sent files.

## Features

- **Download from Multiple Sources**: Download music by name or from YouTube, YouTube Music, Spotify, and Saavn links.
- **Interactive Admin Panel**: A user-friendly, inline keyboard-based panel for managing all bot settings.
- **Group Restriction**: The bot is designed to work only in one allowed group.
- **PM Download Restriction**: Users cannot download music directly in the bot's private chat, except through a specific "Get Song" flow.
- **Two Upload Modes**:
    1.  **Direct Mode**: The bot sends the audio file directly to the group.
    2.  **Info Mode**: The bot sends a message with song details and a "Get Song" button, which redirects the user to the bot's PM to receive the file.
- **Force Subscription**: Users must be subscribed to a designated channel to download music.
- **Persistent Settings**: All admin configurations are saved to a `settings.json` file and persist across bot restarts.
- **PostgreSQL Integration**: Uses a PostgreSQL database to efficiently manage user data for broadcasts and stats.
- **Auto-Deletion of Files**: Automatically deletes sent music files after a configurable amount of time to keep the chat clean.
- **Admin Features via `/panel`**:
    - **Broadcast System**: Admins can broadcast any message to all users or the main group.
    - **Switchable Upload Modes**: Admins can toggle between "direct" and "info" upload modes.
    - **Queue System**: Admins can enable or disable a download queue to manage high traffic.
    - **User Stats**: Admins can view the total number of users in the database.
    - **Configurable Auto-Delete**: Admins can set the auto-delete delay for sent files.
- **High-Quality Audio**: Downloads the best available audio quality (up to 320kbps).
- **Rich Captions**: Uploaded songs include detailed captions with title, artist, album, and an auto-deletion warning.

## Setup and Installation

### 1. Prerequisites

- Python 3.8 or higher
- `ffmpeg` installed on your system.
- A PostgreSQL database.

### 2. Clone the Repository

```bash
git clone <repository-url>
cd <repository-directory>
```

### 3. Install Dependencies

Install the required Python libraries using pip:

```bash
pip install -r requirements.txt
```

### 4. Configuration

Create a `config.py` file by copying the example and filling in your details:

```python
# config.py
BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
API_ID = "YOUR_API_ID"
API_HASH = "YOUR_API_HASH"
ALLOWED_GROUP_ID = "YOUR_ALLOWED_GROUP_ID" # This is the ID of the group where the bot will work
FORCE_SUB_CHANNEL = "@your_channel_username" # The username of the channel for force subscription
ADMINS = ["ADMIN_USER_ID_1", "ADMIN_USER_ID_2"] # List of admin user IDs
SPOTIPY_CLIENT_ID = "YOUR_SPOTIPY_CLIENT_ID"
SPOTIPY_CLIENT_SECRET = "YOUR_SPOTIPY_CLIENT_SECRET"
BOT_USERNAME = "YourBotUsername" # Your bot's username without the '@'

# Default upload mode: 'direct' or 'info'
UPLOAD_MODE = "direct"

# Default queue system status: True or False
QUEUE_ENABLED = False

# PostgreSQL Database URL
DATABASE_URL = "postgresql://user:password@host:port/database"

# Auto-delete delay for sent files in minutes. Set to 0 to disable.
AUTO_DELETE_DELAY = 0
```

**How to get the required values:**

-   **`BOT_TOKEN`**: From [@BotFather](https://t.me/BotFather) on Telegram.
-   **`API_ID`** and **`API_HASH`**: From [my.telegram.org](https://my.telegram.org).
-   **`ALLOWED_GROUP_ID`**: Add the bot to your group and send a message. Then, forward that message to [@userinfobot](https://t.me/userinfobot) to get the group's ID.
-   **`FORCE_SUB_CHANNEL`**: The username of the public channel you want users to subscribe to.
-   **`ADMINS`**: A list of user IDs for those who will have admin privileges on the bot.
-   **`SPOTIPY_CLIENT_ID`** and **`SPOTIPY_CLIENT_SECRET`**: From the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/).
-   **`BOT_USERNAME`**: Your bot's username.
-   **`DATABASE_URL`**: The connection string for your PostgreSQL database. For example: `postgresql://user:password@localhost:5432/music_bot_db`.

### 5. Running the Bot

Once everything is configured, you can start the bot with the following command:

```bash
python bot.py
```

## Admin Commands

-   `/panel`: Opens the interactive admin panel to manage all bot settings.
-   `/cancel`: Cancels any ongoing admin action within the panel.

## How It Works

1.  **Song Request**: A user sends a song name or a supported link in the allowed group.
2.  **Admin Management**: Admins can use the `/panel` command to access a menu-driven interface to configure the bot's settings. All settings are saved and persist after a restart.
3.  **Link Processing**: The bot detects the type of link (YouTube, Spotify, Saavn) and extracts the song information. For Spotify and Saavn, it searches for the song on YouTube.
4.  **Subscription Check**: The bot checks if the user is subscribed to the `FORCE_SUB_CHANNEL`.
5.  **Upload Mode Logic**:
    -   If in **`direct` mode** and the user is subscribed, the bot downloads and sends the song directly to the group.
    -   If in **`info` mode**, the bot sends a message with a "Get Song" button. Clicking this button takes the user to the bot's PM, where they receive the song after another subscription check.
6.  **Queue System**: If the queue is enabled, song requests are added to a queue and processed one by one to avoid overloading the bot.
7.  **User Database**: The bot stores the user ID of anyone who starts a private chat with it in the PostgreSQL database. This is used for the broadcast feature and user statistics.
8.  **Auto-Deletion**: If the auto-delete delay is set to a value greater than 0, the bot will automatically delete the sent music file after the specified number of minutes. A warning is included in the song's caption.