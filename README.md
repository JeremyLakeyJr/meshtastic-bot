# Meshtastic AI DM Bot

A nodeless Meshtastic chatbot that ingests Protobuf over MQTT and sends JSON downlink DMs back into a mesh.

## Features

- **MQTT Integration**: Subscribes to Meshtastic mesh traffic via MQTT
- **Protobuf Parsing**: Parses Meshtastic ServiceEnvelope messages
- **AI Integration**: Uses Google Gemini for intelligent responses
- **Email Integration**: Send and receive emails via Gmail SMTP/IMAP
- **Private Sessions**: Creates private DM sessions for users
- **Chunked Responses**: Sends responses in small chunks with proper pacing

## Setup

1. Set up infrastructure: MQTT server (I use Mosquitto) and an account with read and write permissions for hte bot to use

2. Get yourself a Gemini AI API key

3. Set up a dedicated Gmail account for the bot to use for email sending and receiving. There is a GMAIL_SETUP.md file to go through for that

4. Make sure to include all of the config items in a file named config.env (you can use the config.env.example file as an example)

5. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

6. Run the bot:
   ```bash
   python main.py
   ```

## Usage

### Public Channel Commands
- `/bot` - Start a private session with the bot
- `/weather` - Get weather information (DM required)
- `/email` - Send an email (DM required)
- `/help` - Get help (DM required)

### Private DM Commands
- `/ai <question>` - Ask Gemini a question
- `/weather` - Get weather for your location or specified location
- `/weather <lat,lon>` - Get weather for specific coordinates
- `/weather <City, Country>` - Get weather for specific location
- `/weather clear` - Clear cached location
- `/email <recipient> <subject>` - Send an email
- `/email get <id>` - View email details
- `/email reply <id> <subject>` - Reply to an email
- `/help` - Show all available commands

## Architecture

- **MQTT Client**: Handles mesh traffic ingestion
- **Protobuf Parser**: Decodes Meshtastic messages
- **Session Manager**: Manages user sessions and state
- **AI Handler**: Interfaces with Google Gemini
- **Response Chunker**: Splits responses into appropriate sizes
- **Downlink Publisher**: Sends responses back to the mesh

## Configuration

See `config.env` for all available configuration options.

### Email Setup

The bot uses Gmail for email functionality with **secure authentication methods**. You have two options:

#### Option 1: App Passwords (Personal Gmail)
1. Enable 2-Factor Authentication on your Google Account
2. Generate an App Password for "Mail"
3. Add to `config.env`:
   ```
   GMAIL_EMAIL=your_email@gmail.com
   GMAIL_AUTH_METHOD=app_password
   GMAIL_AUTH_CREDENTIALS=your_app_password
   ```

#### Option 2: OAuth 2.0 Service Account (Recommended, Works with Workspace)
1. Follow the OAuth 2.0 setup guide: `python setup_oauth2.py`
2. Add to `config.env`:
   ```
   GMAIL_EMAIL=your_email@gmail.com
   GMAIL_AUTH_METHOD=oauth2_service_account
   GMAIL_AUTH_CREDENTIALS=/path/to/service-account.json
   ```

#### Option 3: OAuth 2.0 User Consent (Recommended for Personal Gmail)
1. Follow the personal OAuth 2.0 setup guide: `python setup_personal_oauth2.py`
2. Add to `config.env`:
   ```
   GMAIL_EMAIL=your_email@gmail.com
   GMAIL_AUTH_METHOD=oauth2_user_consent
   GMAIL_AUTH_CREDENTIALS=token.json
   ```

**Note**: App Passwords only work with personal Gmail accounts. Google Workspace accounts require OAuth 2.0.

### Email Features

- **Outgoing Emails**: Send emails to any recipient with subject and body
- **Email Tracking**: Each email gets a unique ID for later reference
- **Reply Handling**: Automatically relay email replies back to Meshtastic users
- **Email History**: View and manage your sent/received emails
- **Two-way Communication**: Full email conversation flow between Meshtastic and email users
