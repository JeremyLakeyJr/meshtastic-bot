#!/usr/bin/env python3
"""
Personal Gmail OAuth2 Setup for Meshtastic Bot
This script sets up OAuth2 authentication for personal Gmail accounts.
"""

import os
import json
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# Gmail API scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'
]

def setup_personal_oauth2():
    """Setup OAuth2 for personal Gmail account."""
    print("🔐 Personal Gmail OAuth2 Setup")
    print("=" * 50)
    print()
    print("This setup is for personal Gmail accounts (like meshtasticbot@gmail.com)")
    print("It will create a credentials.json file that you can use for authentication.")
    print()
    
    # Check if credentials.json exists
    if os.path.exists('credentials.json'):
        print("✓ Found existing credentials.json file")
        print("If you want to create new credentials, delete this file first.")
        return
    
    # Check if the service account file exists (for reference)
    if os.path.exists('effortless-leaf-470117-r9-a4a7b7ac26db.json'):
        print("ℹ️  Found your service account file: effortless-leaf-470117-r9-a4a7b7ac26db.json")
        print("Note: This is a service account file, not OAuth2 client credentials.")
        print("For personal OAuth2 setup, you need to create OAuth2 client credentials.")
        print()
    
    print("📋 Step-by-Step Setup:")
    print()
    print("⚠️  IMPORTANT: This is DIFFERENT from the service account file you already have!")
    print("   - Service Account = for domain-wide delegation (what you have)")
    print("   - OAuth2 Client ID = for personal Gmail authentication (what you need)")
    print()
    print("1. Go to Google Cloud Console: https://console.cloud.google.com/")
    print("2. Create a new project or select existing one")
    print("3. Enable Gmail API:")
    print("   - Go to 'APIs & Services' → 'Library'")
    print("   - Search for 'Gmail API' and enable it")
    print("4. Create OAuth 2.0 Client ID:")
    print("   - Go to 'APIs & Services' → 'Credentials'")
    print("   - Click 'Create Credentials' → 'OAuth client ID'")
    print("   - Choose 'Desktop application' as application type")
    print("   - Give it a name (e.g., 'Meshtastic Bot')")
    print("   - Click 'Create'")
    print("5. Download the JSON file and rename it to 'credentials.json'")
    print("6. Place 'credentials.json' in this directory")
    print()
    
    input("Press Enter when you have created and downloaded credentials.json...")
    
    if not os.path.exists('credentials.json'):
        print("❌ credentials.json not found!")
        print("Please download the OAuth 2.0 client credentials and place them here.")
        return
    
    print("✓ Found credentials.json")
    print("Now setting up OAuth2 authentication...")
    
    try:
        # Load client secrets
        with open('credentials.json', 'r') as f:
            client_secrets = json.load(f)
        
        # Create OAuth flow
        flow = InstalledAppFlow.from_client_config(
            client_secrets, SCOPES)
        
        # Run local server for authorization
        print("🌐 Opening browser for authorization...")
        print("Please authorize the application in your browser.")
        print("After authorization, you'll be redirected to a local server.")
        
        creds = flow.run_local_server(port=0)
        
        # Save credentials
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
        
        print("✓ OAuth2 authentication successful!")
        print("✓ Credentials saved to token.json")
        print()
        print("🔧 Next steps:")
        print("1. Update your config.env:")
        print("   GMAIL_AUTH_METHOD=oauth2_user_consent")
        print("   GMAIL_AUTH_CREDENTIALS=token.json")
        print("2. Test with: python test_email.py")
        
    except Exception as e:
        print(f"❌ OAuth2 setup failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    setup_personal_oauth2()
