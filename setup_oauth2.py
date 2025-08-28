#!/usr/bin/env python3
"""
OAuth 2.0 Setup Helper for Meshtastic Bot
This script helps you set up OAuth 2.0 authentication for Gmail.
"""

import os
import json
import sys

def print_setup_instructions():
    """Print step-by-step OAuth 2.0 setup instructions."""
    print("🔐 OAuth 2.0 Setup for Gmail (Most Secure Method)")
    print("=" * 60)
    print()
    print("This method is required for Google Workspace accounts and recommended for all users.")
    print()
    
    print("📋 Step-by-Step Setup:")
    print()
    print("1. Go to Google Cloud Console: https://console.cloud.google.com/")
    print("2. Create a new project or select existing one")
    print("3. Enable Gmail API:")
    print("   - Go to 'APIs & Services' → 'Library'")
    print("   - Search for 'Gmail API' and enable it")
    print("4. Create Service Account:")
    print("   - Go to 'APIs & Services' → 'Credentials'")
    print("   - Click 'Create Credentials' → 'Service Account'")
    print("   - Fill in details and create")
    print("5. Generate JSON Key:")
    print("   - Click on your service account")
    print("   - Go to 'Keys' tab")
    print("   - Click 'Add Key' → 'Create new key' → 'JSON'")
    print("   - Download the JSON file")
    print()
    
    print("🔑 For Google Workspace (Domain) Users:")
    print("6. Enable Domain-Wide Delegation:")
    print("   - In service account details, check 'Enable Google Workspace Domain-wide Delegation'")
    print("   - Note the Client ID")
    print("7. Grant permissions:")
    print("   - Your Google Workspace admin needs to authorize the service account")
    print("   - The scope is: https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly")
    print()
    
    print("📁 For Personal Gmail Users:")
    print("6. Share your Gmail with the service account:")
    print("   - The service account email will be in your JSON file")
    print("   - Add it as a delegate in Gmail settings")
    print()

def create_config_template():
    """Create a config template for OAuth 2.0."""
    print("📝 Configuration Template:")
    print()
    print("Add these lines to your config.env:")
    print()
    print("GMAIL_EMAIL=your_email@gmail.com")
    print("GMAIL_AUTH_METHOD=oauth2_service_account")
    print("GMAIL_AUTH_CREDENTIALS=/path/to/your-service-account.json")
    print()
    print("OR put the entire JSON content in the environment variable:")
    print()
    print("GMAIL_EMAIL=your_email@gmail.com")
    print("GMAIL_AUTH_METHOD=oauth2_service_account")
    print("GMAIL_AUTH_CREDENTIALS={\"type\": \"service_account\", ...}")
    print()

def validate_json_file(file_path):
    """Validate a service account JSON file."""
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        required_fields = ['type', 'project_id', 'private_key_id', 'private_key', 'client_email']
        missing_fields = [field for field in required_fields if field not in data]
        
        if missing_fields:
            print(f"❌ Invalid service account JSON. Missing fields: {missing_fields}")
            return False
        
        if data.get('type') != 'service_account':
            print("❌ Invalid service account JSON. 'type' should be 'service_account'")
            return False
        
        print("✅ Valid service account JSON file!")
        print(f"   Project ID: {data.get('project_id')}")
        print(f"   Service Account Email: {data.get('client_email')}")
        return True
        
    except FileNotFoundError:
        print(f"❌ File not found: {file_path}")
        return False
    except json.JSONDecodeError:
        print(f"❌ Invalid JSON file: {file_path}")
        return False
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return False

def main():
    """Main function."""
    print_setup_instructions()
    
    if len(sys.argv) > 1:
        # User provided a JSON file path to validate
        json_file = sys.argv[1]
        print(f"🔍 Validating JSON file: {json_file}")
        print()
        validate_json_file(json_file)
    else:
        # Show configuration template
        create_config_template()
        
        # Ask if user wants to validate a file
        print("💡 Tip: You can validate your JSON file by running:")
        print(f"   python {sys.argv[0]} /path/to/your-service-account.json")
        print()

if __name__ == "__main__":
    main()
