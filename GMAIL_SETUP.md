# Gmail Setup for Meshtastic Bot

## Important: Gmail Security Requirements

Google is phasing out "less secure app access" for security reasons. Starting January 2025, this option will no longer work for Google Workspace accounts. You must use one of the secure methods below.

## Option 1: Enable "Less Secure App Access" (Not Recommended)

1. Go to your Google Account settings: https://myaccount.google.com/
2. Navigate to Security → Less secure app access
3. Turn ON "Allow less secure apps"
4. Use your regular Gmail password in `config.env`

**Warning**: This option is less secure and may be disabled by Google.

## Option 2: Use App Passwords (For Personal Gmail)

1. Enable 2-Factor Authentication on your Google Account
2. Go to Security → App passwords
3. Generate a new app password for "Mail"
4. Use this generated password in `config.env`

**Note**: App Passwords only work with personal Gmail accounts, not Google Workspace accounts.

## Option 3: OAuth 2.0 with Service Account (Most Secure - Recommended for Workspace)

This is the most secure method and what Google recommends for production applications.

## Option 4: OAuth 2.0 with User Consent (Recommended for Personal Gmail)

This is the best method for personal Gmail accounts like meshtasticbot@gmail.com.

### Setup Steps:

1. **Go to Google Cloud Console**: https://console.cloud.google.com/
2. **Create a new project** or select existing one
3. **Enable Gmail API**:
   - Go to "APIs & Services" → "Library"
   - Search for "Gmail API" and enable it
4. **Create OAuth 2.0 Client ID**:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "OAuth client ID"
   - Choose "Desktop application" as application type
   - Give it a name (e.g., "Meshtastic Bot")
   - Click "Create"
5. **Download the JSON file** and rename it to `credentials.json`
6. **Run the setup script**:
   ```bash
   python setup_personal_oauth2.py
   ```
7. **Follow the browser authorization** process
8. **Update your config.env**:
   ```bash
   GMAIL_AUTH_METHOD=oauth2_user_consent
   GMAIL_AUTH_CREDENTIALS=token.json
   ```

**Advantages**:
- Works with personal Gmail accounts
- No domain-wide delegation required
- Secure OAuth2 flow
- Automatic token refresh

### Setup Steps:

1. **Go to Google Cloud Console**: https://console.cloud.google.com/
2. **Create a new project** or select existing one
3. **Enable Gmail API**:
   - Go to "APIs & Services" → "Library"
   - Search for "Gmail API" and enable it
4. **Create Service Account**:
   - Go to "APIs & Services" → "Credentials"
   - Click "Create Credentials" → "Service Account"
   - Fill in details and create
5. **Generate JSON Key**:
   - Click on your service account
   - Go to "Keys" tab
   - Click "Add Key" → "Create new key" → "JSON"
   - Download the JSON file
6. **Enable Domain-Wide Delegation** (if using Google Workspace):
   - In service account details, check "Enable Google Workspace Domain-wide Delegation"
   - Note the Client ID
7. **Grant permissions** (for Google Workspace):
   - Your Google Workspace admin needs to authorize the service account
   - The scope is: `https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly`

## Configuration

### For App Password Authentication:

```bash
GMAIL_EMAIL=your_email@gmail.com
GMAIL_AUTH_METHOD=app_password
GMAIL_AUTH_CREDENTIALS=your_app_password_here
```

### For OAuth 2.0 Service Account:

```bash
GMAIL_EMAIL=your_email@gmail.com
GMAIL_AUTH_METHOD=oauth2_service_account
GMAIL_AUTH_CREDENTIALS=/path/to/service-account.json
```

**OR** put the entire JSON content in the environment variable:

```bash
GMAIL_EMAIL=your_email@gmail.com
GMAIL_AUTH_METHOD=oauth2_service_account
GMAIL_AUTH_CREDENTIALS={"type": "service_account", "project_id": "...", ...}
```

### For OAuth 2.0 User Consent (Personal Gmail):

```bash
GMAIL_EMAIL=your_email@gmail.com
GMAIL_AUTH_METHOD=oauth2_user_consent
GMAIL_AUTH_CREDENTIALS=token.json
```

## Testing

After setup, test the email functionality:

```bash
python test_email.py
```

## Troubleshooting

- **Authentication Failed**: Check your credentials and ensure you're using an App Password if 2FA is enabled
- **SMTP Error**: Verify your Gmail account allows programmatic access
- **IMAP Error**: Ensure IMAP is enabled in your Gmail settings

## Security Notes

- Never commit your `config.env` file to version control
- Use App Passwords instead of your main password
- Regularly rotate your App Passwords
- Monitor your Gmail account for suspicious activity
