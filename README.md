# Telegram Music Bot

This is a powerful Telegram bot for processing media from various sources, designed to work exclusively within a specified group. It includes features like link detection, force subscription, multiple upload modes, a broadcast system, a queue to manage high traffic, and auto-deletion of sent files.

## Features

- **Process Media from Links**: Handles media requests from various links and by name.
- **Interactive Admin Panel**: A user-friendly, inline keyboard-based panel for managing all bot settings.
- **Group Restriction**: The bot is designed to work only in one allowed group.
- **Persistent Settings**: All admin configurations are saved to a PostgreSQL database and persist across bot restarts.
- **Auto-Deletion of Files**: Automatically deletes sent media files after a configurable amount of time.
- **Docker Support**: Comes with `Dockerfile` and `docker-compose.yml` for easy, one-command deployment.

## Deployment

There are two ways to deploy this bot: using Docker (recommended) or running it manually.

### 1. Deploy with Docker (Recommended)

This is the easiest way to get the bot running, as it automatically handles the database and all dependencies, including `ffmpeg`.

**Prerequisites:**
- [Docker](https://docs.docker.com/get-docker/)
- [Docker Compose](https://docs.docker.com/compose/install/)

**Steps:**
1.  **Clone the Repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```
2.  **Configure the Bot:**
    -   Open the `config.py` file and fill in your bot's details (`BOT_TOKEN`, `ALLOWED_GROUP_ID`, `ADMINS`, etc.).
    -   **Do not** change the `DATABASE_URL` in this file. Docker Compose will handle it.
3.  **Run with Docker Compose:**
    ```bash
    docker-compose up --build -d
    ```
The bot and its database are now running in the background. To view logs, use `docker-compose logs -f`. To stop, use `docker-compose down`.

---

### 2. Manual Installation

**Prerequisites:**
- Python 3.8 or higher
- `ffmpeg` installed on your system.
- A running PostgreSQL database.

**Steps:**
1.  **Clone the Repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```
2.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3.  **Configure the Bot:**
    -   Open the `config.py` file and fill in all your details, including the `DATABASE_URL` for your PostgreSQL database.
4.  **Running the Bot:**
    ```bash
    python bot.py
    ```

## Admin Commands

-   `/panel`: Opens the interactive admin panel to manage all bot settings.
-   `/cancel`: Cancels any ongoing admin action within the panel.

## How It Works

1.  **Media Request**: A user sends a supported link or a name in the allowed group.
2.  **Admin Management**: Admins use the `/panel` command to access a menu-driven interface to configure the bot's settings.
3.  **Link Processing**: The bot processes the link to retrieve the media information.
4.  **Subscription Check**: The bot checks if the user is subscribed to the `FORCE_SUB_CHANNEL`. **Note: The bot must be an administrator in this channel for the subscription check to work.**
5.  **Upload Mode Logic**: Based on the admin-configured mode, the bot either sends the file directly to the group or provides a button to get the file in a private message.
6.  **Queue System**: If enabled, requests are added to a queue and processed sequentially.
7.  **User Database**: The bot stores user IDs in the PostgreSQL database for the broadcast and stats features.
8.  **Auto-Deletion**: If enabled, the bot automatically deletes the sent media file after the configured delay.