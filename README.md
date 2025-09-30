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

### 2. Deploy to Choreo

You can deploy this bot to [Choreo](https://console.choreo.dev/) for a managed deployment experience.

**Steps:**
1.  **Fork this Repository** to your GitHub account.
2.  **Create a New Project** in Choreo and connect your GitHub account.
3.  **Select the Repository**: Choreo will automatically detect the `component.yaml` file and configure the bot as a "Bot" component with the correct health check endpoint.
4.  **Configure Environment Variables**: In the Choreo console, go to "Deploy" -> "Configure & Deploy". You will need to add the following environment variables:
    -   `BOT_TOKEN`
    -   `ALLOWED_GROUP_ID`
    -   `ADMINS`
    -   `FORCE_SUB_CHANNEL`
    -   `SPOTIPY_CLIENT_ID`
    -   `SPOTIPY_CLIENT_SECRET`
    -   `BOT_USERNAME`
    -   `DATABASE_URL` (You can get this from a managed database provider or Choreo's marketplace).
5.  **Deploy**: Click "Deploy". Choreo will build and deploy the bot using the predefined settings.

---

### 3. Manual Installation

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
    -   The bot is configured via environment variables. Make sure to set `BOT_TOKEN`, `ALLOWED_GROUP_ID`, `DATABASE_URL`, and `ADMINS` before running.
4.  **Running the Bot:**
    ```bash
    python bot.py
    ```

---

### 4. Deploy on Termux (for Local Testing)

This method allows you to run the bot on an Android device using the Termux terminal emulator, which is useful for local testing and development.

**Prerequisites:**
- [Termux](https://f-droid.org/en/packages/com.termux/) installed on your Android device.
- A PostgreSQL database. Since installing PostgreSQL on Termux can be complex, it is highly recommended to use a free cloud provider like [Supabase](https://supabase.com/database), [Neon](https://neon.tech), or [ElephantSQL](https://www.elephantsql.com/).

**Steps:**

1.  **Update Termux Packages:**
    Open Termux and run the following commands to ensure all packages are up to date:
    ```bash
    pkg update && pkg upgrade
    ```

2.  **Install Dependencies:**
    Install `git`, `python`, and `ffmpeg`, which are required to run the bot:
    ```bash
    pkg install git python ffmpeg
    ```

3.  **Clone the Repository:**
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```

4.  **Set Up a Virtual Environment (Recommended):**
    Using a virtual environment prevents conflicts with other Python projects.
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```
    *To deactivate the virtual environment later, simply run `deactivate`.*

5.  **Install Python Libraries:**
    Install all the required Python libraries from the `requirements.txt` file.
    ```bash
    pip install -r requirements.txt
    ```

6.  **Configure Environment Variables:**
    The bot is configured using environment variables. You can set them for your current session like this. **Remember to replace the placeholder values with your actual credentials.**
    ```bash
    export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
    export ALLOWED_GROUP_ID="YOUR_ALLOWED_GROUP_ID"
    export DATABASE_URL="YOUR_POSTGRESQL_DATABASE_URL"
    export ADMINS="ADMIN_ID_1,ADMIN_ID_2"
    # --- Optional Variables ---
    export BOT_USERNAME="YOUR_BOT_USERNAME"
    export FORCE_SUB_CHANNEL="@your_channel_username"
    export SPOTIPY_CLIENT_ID="YOUR_SPOTIFY_ID"
    export SPOTIPY_CLIENT_SECRET="YOUR_SPOTIFY_SECRET"
    ```
    **Note:** These variables are only set for the current Termux session. If you close and reopen Termux, you will need to export them again.

7.  **Running the Bot:**
    Once the dependencies are installed and the environment variables are set, you can start the bot:
    ```bash
    python bot.py
    ```
    The bot should now be running on your device.

## Troubleshooting

### Dealing with YouTube's "Sign In" Error (Using Cookies)

Occasionally, YouTube may block downloads from servers or hosting platforms, resulting in an error like `Sign in to confirm you’re not a bot`. To solve this, you must provide the bot with your YouTube cookies.

The only supported method for providing cookies is through an environment variable. This is the most reliable approach for all deployment types, especially on stateless platforms like Choreo.

**Steps:**

1.  **Export Your Cookies:**
    -   Install a browser extension that can export cookies in the Netscape format (e.g., "Cookie-Editor" for Chrome/Firefox).
    -   Go to `youtube.com` and make sure you are logged in.
    -   Use the extension to export all cookies for the `youtube.com` domain.

2.  **Set the Environment Variable:**
    -   Create a new environment variable named `YOUTUBE_COOKIES_CONTENT`.
    -   Paste the **entire content** of your exported cookies as the value for this variable.

The bot is designed to handle both single-line and multi-line cookie strings, so you can paste the content directly. It will automatically detect this environment variable on startup, write the cookies to a temporary file, and use them for all subsequent download requests.

---

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