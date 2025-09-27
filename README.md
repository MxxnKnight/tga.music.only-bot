# Telegram Music Bot

This is a powerful Telegram bot for processing media from various sources, designed to work exclusively within a specified group. It includes features like link detection, force subscription, multiple upload modes, a broadcast system, a queue to manage high traffic, and auto-deletion of sent files.

## Features

- **Process Media from Links**: Handles media requests from various links and by name.
- **Interactive Admin Panel**: A user-friendly, inline keyboard-based panel for managing all bot settings.
- **Group Restriction**: The bot is designed to work only in one allowed group.
- **Two Upload Modes**:
    1.  **Direct Mode**: The bot sends the media file directly to the group.
    2.  **Info Mode**: The bot sends a message with media details and a "Get Media" button, which redirects the user to the bot's PM to receive the file.
- **Force Subscription**: Users must be subscribed to a designated channel to receive files.
- **Persistent Settings**: All admin configurations are saved to the database and persist across bot restarts.
- **PostgreSQL Integration**: Uses a PostgreSQL database to efficiently manage user data and settings.
- **Auto-Deletion of Files**: Automatically deletes sent media files after a configurable amount of time.
- **Admin Features via `/panel`**:
    - **Broadcast System**: Admins can broadcast any message to all users or the main group.
    - **Switchable Upload Modes**: Admins can toggle between "direct" and "info" upload modes.
    - **Queue System**: Admins can enable or disable a processing queue to manage high traffic.
    - **User Stats**: Admins can view the total number of users in the database.
    - **Configurable Auto-Delete**: Admins can set the auto-delete delay for sent files.
- **High-Quality Audio**: Processes the best available audio quality.
- **Rich Captions**: Uploaded files include detailed captions with title, artist, and album information.

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

Fill in your details in the `config.py` file. You will need to obtain API keys and tokens from their respective platforms.

### 5. Running the Bot

Once everything is configured, you can start the bot with the following command:

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