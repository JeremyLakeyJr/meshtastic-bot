#!/usr/bin/env python3
"""
Email Handler for Meshtastic Bot
Handles email sending via SMTP, email receiving via IMAP, and email storage/retrieval.
Supports both OAuth 2.0 (service accounts) and App Passwords for secure Gmail access.
"""

import smtplib
import imaplib
import email
import uuid
import time
import logging
import threading
import json
import os
import base64
import random
import string
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import decode_header
from typing import Dict, Optional, Tuple, List, Union
from dataclasses import dataclass, asdict

# OAuth 2.0 imports
try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.oauth2 import service_account
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    OAUTH_AVAILABLE = True
except ImportError:
    OAUTH_AVAILABLE = False
    logging.warning("OAuth 2.0 libraries not available. Install with: pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client")

# Gmail API scopes
SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify'
]

logger = logging.getLogger(__name__)

@dataclass
class EmailMessage:
    """Represents an email message with all necessary metadata."""
    unique_id: str
    sender_meshtastic_id: int
    sender_email: str
    recipient_email: str
    subject: str
    body: str
    timestamp: float
    direction: str  # 'outgoing' or 'incoming'
    reply_to_id: Optional[str] = None  # For replies to track conversation threads
    message_id: Optional[str] = None  # For email threading (In-Reply-To, References)

class EmailHandler:
    """Handles all email operations for the Meshtastic bot with secure authentication."""
    
    def __init__(self, gmail_email: str, auth_method: str = "app_password", 
                 auth_credentials: Union[str, dict] = None):
        """
        Initialize email handler with secure authentication.
        
        Args:
            gmail_email: Gmail address to use
            auth_method: "oauth2_service_account" or "app_password"
            auth_credentials: For OAuth2: path to service account JSON or dict
                            For App Password: the app password string
        """
        self.gmail_email = gmail_email
        self.auth_method = auth_method
        self.auth_credentials = auth_credentials
        
        # Email server settings
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.imap_server = "imap.gmail.com"
        self.imap_port = 993
        
        # OAuth 2.0 settings
        self.oauth_creds = None
        self.gmail_service = None
        
        # Storage for email messages
        self.emails_file = "emails.json"
        self.emails: Dict[str, EmailMessage] = {}
        self._load_emails()
        
        # Initialize authentication
        self._setup_authentication()
        
        # Start monitoring thread for incoming emails
        self.monitoring = False
        self.monitor_thread = None
        self.start_monitoring()
    
    def _setup_authentication(self):
        """Setup authentication based on the chosen method."""
        if self.auth_method == "oauth2_service_account":
            if not OAUTH_AVAILABLE:
                raise ValueError("OAuth 2.0 libraries not available. Install required packages.")
            self._setup_oauth2_service_account()
        elif self.auth_method == "oauth2_user_consent":
            if not OAUTH_AVAILABLE:
                raise ValueError("OAuth 2.0 libraries not available. Install required packages.")
            self._setup_oauth2_user_consent()
        elif self.auth_method == "app_password":
            self._setup_app_password()
        else:
            raise ValueError(f"Unsupported auth method: {self.auth_method}")
    
    def _setup_oauth2_service_account(self):
        """Setup OAuth 2.0 authentication using service account."""
        try:
            if isinstance(self.auth_credentials, str):
                # Load from JSON file
                with open(self.auth_credentials, 'r') as f:
                    service_account_info = json.load(f)
            else:
                # Use provided dict
                service_account_info = self.auth_credentials
            
            # Create credentials with proper scopes
            self.oauth_creds = service_account.Credentials.from_service_account_info(
                service_account_info,
                scopes=['https://www.googleapis.com/auth/gmail.send',
                       'https://www.googleapis.com/auth/gmail.readonly',
                       'https://www.googleapis.com/auth/gmail.modify']
            )
            
            # For domain-wide delegation, impersonate the user
            if hasattr(self.oauth_creds, 'with_subject'):
                self.oauth_creds = self.oauth_creds.with_subject(self.gmail_email)
            
            # Build Gmail service
            self.gmail_service = build('gmail', 'v1', credentials=self.oauth_creds)
            
            logger.info("OAuth 2.0 service account authentication setup successful")
            
        except Exception as e:
            logger.error(f"Failed to setup OAuth 2.0: {e}")
            raise
    
    def _setup_app_password(self):
        """Setup App Password authentication."""
        if not self.auth_credentials:
            raise ValueError("App password required for app_password authentication method")
        
        logger.info("App password authentication setup successful")
    
    def _setup_oauth2_user_consent(self):
        """Setup OAuth 2.0 authentication using user consent flow."""
        try:
            if not os.path.exists(self.auth_credentials):
                raise FileNotFoundError(f"Token file not found: {self.auth_credentials}")
            
            # Load credentials from token file
            with open(self.auth_credentials, 'r') as f:
                creds_data = json.load(f)
            
            self.oauth_creds = Credentials.from_authorized_user_info(creds_data, SCOPES)
            
            # Refresh token if needed
            if self.oauth_creds and self.oauth_creds.expired and self.oauth_creds.refresh_token:
                self.oauth_creds.refresh(Request())
                # Save updated token
                with open(self.auth_credentials, 'w') as token:
                    token.write(self.oauth_creds.to_json())
            
            # Build Gmail service
            self.gmail_service = build('gmail', 'v1', credentials=self.oauth_creds)
            
            logger.info("OAuth 2.0 user consent authentication setup successful")
            
        except Exception as e:
            logger.error(f"Failed to setup OAuth 2.0 user consent: {e}")
            raise
    
    def _get_smtp_connection(self):
        """Get authenticated SMTP connection."""
        if self.auth_method in ["oauth2_service_account", "oauth2_user_consent"]:
            return self._get_oauth2_smtp_connection()
        else:
            return self._get_app_password_smtp_connection()
    
    def _get_oauth2_smtp_connection(self):
        """Get OAuth 2.0 authenticated SMTP connection."""
        try:
            # OAuth2 SMTP is complex and unreliable with Gmail
            # We'll use the Gmail API instead for sending emails
            logger.info("OAuth2 SMTP not implemented - using Gmail API for sending")
            
            # Return a dummy connection that will be handled by send_email method
            class DummySMTP:
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
                def send_message(self, msg):
                    # This will be overridden in send_email method
                    pass
            
            return DummySMTP()
            
        except Exception as e:
            logger.error(f"OAuth 2.0 SMTP connection failed: {e}")
            raise
    
    def _get_app_password_smtp_connection(self):
        """Get App Password authenticated SMTP connection."""
        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.starttls()
            server.login(self.gmail_email, self.auth_credentials)
            return server
        except Exception as e:
            logger.error(f"App password SMTP connection failed: {e}")
            raise
    
    def _get_imap_connection(self):
        """Get authenticated IMAP connection."""
        if self.auth_method in ["oauth2_service_account", "oauth2_user_consent"]:
            return self._get_oauth2_imap_connection()
        else:
            return self._get_app_password_imap_connection()
    
    def _get_oauth2_imap_connection(self):
        """Get OAuth 2.0 authenticated IMAP connection."""
        try:
            # For IMAP with OAuth 2.0, we need to use the Gmail API instead
            # This is more complex and requires different approach
            logger.warning("OAuth 2.0 IMAP not fully implemented. Using Gmail API for inbox monitoring.")
            return None
        except Exception as e:
            logger.error(f"OAuth 2.0 IMAP connection failed: {e}")
            raise
    
    def _get_app_password_imap_connection(self):
        """Get App Password authenticated IMAP connection."""
        try:
            imap = imaplib.IMAP4_SSL(self.imap_server, self.imap_port)
            imap.login(self.gmail_email, self.auth_credentials)
            return imap
        except Exception as e:
            logger.error(f"App password IMAP connection failed: {e}")
            raise
    
    def _load_emails(self):
        """Load emails from persistent storage."""
        try:
            if os.path.exists(self.emails_file):
                with open(self.emails_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for email_id, email_data in data.items():
                        # Handle migration for existing emails without message_id
                        if 'message_id' not in email_data:
                            email_data['message_id'] = f"<{email_id}@meshtastic.local>"
                        self.emails[email_id] = EmailMessage(**email_data)
                logger.info(f"Loaded {len(self.emails)} emails from storage")
        except Exception as e:
            logger.warning(f"Could not load emails: {e}")
    
    def _save_emails(self):
        """Save emails to persistent storage."""
        try:
            with open(self.emails_file, 'w', encoding='utf-8') as f:
                data = {email_id: asdict(email_msg) for email_id, email_msg in self.emails.items()}
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save emails: {e}")
    
    def send_email(self, sender_meshtastic_id: int, sender_email: str, 
                   recipient_email: str, subject: str, body: str, 
                   reply_to_id: Optional[str] = None) -> Tuple[bool, str]:
        """Send an email via SMTP and store it."""
        try:
            # Create unique ID for this email
            unique_id = self._generate_short_id()
            
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = self.gmail_email
            msg['To'] = recipient_email
            msg['Subject'] = subject
            
            # Generate a proper Message-ID for threading
            # When using SMTP, Gmail will use our Message-ID header
            import uuid
            message_id = f"<{unique_id}.{uuid.uuid4().hex[:8]}@meshtastic.local>"
            msg['Message-ID'] = message_id
            
            # Add Meshtastic sender ID to headers for tracking
            msg['X-Meshtastic-Sender-ID'] = str(sender_meshtastic_id)
            msg['X-Meshtastic-Email-ID'] = unique_id
            
            # If this is a reply, add proper threading headers
            if reply_to_id:
                logger.info(f"Setting up threading for reply to email {reply_to_id}")
                # Find the original email to get its Message-ID
                original_email = self.emails.get(reply_to_id)
                if original_email:
                    logger.info(f"Found original email: {original_email.subject}")
                    
                    # For proper email threading, we ALWAYS need to trace back to the root email
                    # and use its Message-ID for In-Reply-To and References headers
                    # This ensures Gmail groups all emails in the conversation together
                    root_email_id = self._find_root_email_id(reply_to_id)
                    root_email = self.emails.get(root_email_id) if root_email_id else None
                    
                    if root_email and root_email.message_id:
                        # Use the root email's Message-ID for proper threading
                        # This will be our generated Message-ID format
                        msg['In-Reply-To'] = root_email.message_id
                        msg['References'] = root_email.message_id
                        logger.info(f"Added reply headers using root email {root_email_id}: In-Reply-To={msg['In-Reply-To']}")
                    else:
                        # Last resort: use our internal format for the root email
                        msg['In-Reply-To'] = f"<{root_email_id or reply_to_id}@meshtastic.local>"
                        msg['References'] = f"<{root_email_id or reply_to_id}@meshtastic.local>"
                        logger.info(f"Added reply headers using internal format for root email {root_email_id or reply_to_id}")
                else:
                    logger.warning(f"Could not find original email {reply_to_id} for threading")
            else:
                logger.info("This is not a reply email")
            
            # Create email body with footer
            footer = f"\n\n---\nThis message was forwarded from a bot on the Meshtastic network.\nOriginally crafted by Meshtastic user ID: {sender_meshtastic_id}\nYou can reply to this email to send a message back to the Meshtastic user."
            full_body = body + footer
            
            msg.attach(MIMEText(full_body, 'plain', 'utf-8'))
            
            # Send via appropriate method
            gmail_message_id = None
            if self.auth_method in ["oauth2_service_account", "oauth2_user_consent"]:
                # Use Gmail API for OAuth2
                gmail_message_id = self._send_via_gmail_api(msg)
            else:
                # Use SMTP for app password
                with self._get_smtp_connection() as server:
                    server.send_message(msg)
            
            # Store the email with our generated Message-ID for proper threading
            # Even though Gmail generates internal IDs, we'll use our format for threading
            final_message_id = message_id
            email_msg = EmailMessage(
                unique_id=unique_id,
                sender_meshtastic_id=sender_meshtastic_id,
                sender_email=sender_email,
                recipient_email=recipient_email,
                subject=subject,
                body=body,
                timestamp=time.time(),
                direction='outgoing',
                reply_to_id=reply_to_id,  # CRITICAL: Set reply_to_id for threading
                message_id=final_message_id  # Use our generated Message-ID for threading
            )
            self.emails[unique_id] = email_msg
            self._save_emails()
            
            logger.info(f"Email sent successfully with ID: {unique_id}")
            if reply_to_id:
                logger.info(f"  Stored with reply_to_id: {reply_to_id} for threading")
            else:
                logger.info(f"  Stored as new email (no threading)")
            return True, unique_id
            
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False, str(e)
    
    def _generate_short_id(self) -> str:
        """Generate a short, memorable email ID."""
        # Format: 2 letters + 3 digits (e.g., AB123, XY789)
        letters = ''.join(random.choices(string.ascii_uppercase, k=2))
        digits = ''.join(random.choices(string.digits, k=3))
        short_id = f"{letters}{digits}"
        
        # Ensure uniqueness
        while short_id in self.emails:
            letters = ''.join(random.choices(string.ascii_uppercase, k=2))
            digits = ''.join(random.choices(string.digits, k=3))
            short_id = f"{letters}{digits}"
        
        return short_id

    def _send_via_gmail_api(self, msg):
        """Send email via Gmail API instead of SMTP."""
        try:
            if not self.gmail_service:
                raise ValueError("Gmail service not initialized")
            
            # Convert MIME message to raw email format
            raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
            
            # Send via Gmail API
            message = self.gmail_service.users().messages().send(
                userId='me', 
                body={'raw': raw_message}
            ).execute()
            
            gmail_id = message.get('id')
            logger.info(f"Email sent via Gmail API: {gmail_id}")
            
            # Return the Gmail ID for reference (not used for threading)
            return gmail_id
            
        except Exception as e:
            logger.error(f"Failed to send email via Gmail API: {e}")
            raise
    def get_email(self, unique_id: str) -> Optional[EmailMessage]:
        """Retrieve an email by its unique ID."""
        return self.emails.get(unique_id)
    
    def get_emails_for_user(self, meshtastic_user_id: int) -> List[EmailMessage]:
        """Get all emails for a specific Meshtastic user."""
        return [email_msg for email_msg in self.emails.values() 
                if email_msg.sender_meshtastic_id == meshtastic_user_id]
    
    def get_email_thread(self, email_id: str) -> List[EmailMessage]:
        """Get the complete email thread for a given email ID."""
        thread = []
        current_id = email_id
        
        # First, find the root email (the one with no reply_to_id)
        while current_id and current_id in self.emails:
            email = self.emails[current_id]
            thread.insert(0, email)  # Insert at beginning to maintain order
            current_id = email.reply_to_id
        
        # Then find all emails that reply to this thread
        # Use a set to avoid duplicates
        thread_ids = {e.unique_id for e in thread}
        for email in self.emails.values():
            if email.reply_to_id in thread_ids and email.unique_id not in thread_ids:
                thread.append(email)
                thread_ids.add(email.unique_id)
        
        return sorted(thread, key=lambda x: x.timestamp)
    
    def _find_root_email_id(self, email_id: str) -> Optional[str]:
        """Find the root email ID in a conversation chain."""
        current_id = email_id
        visited = set()  # Prevent infinite loops
        
        # Trace back through the reply chain to find the root email
        while current_id and current_id in self.emails and current_id not in visited:
            visited.add(current_id)
            email = self.emails[current_id]
            
            if not email.reply_to_id:
                # This is the root email (no reply_to_id)
                logger.info(f"Found root email: {current_id} (subject: {email.subject})")
                return current_id
            
            current_id = email.reply_to_id
        
        # If we can't find a root, return the original email_id
        logger.info(f"Could not find root email, returning original: {email_id}")
        return email_id
    
    def debug_email_threading(self, email_id: str) -> str:
        """Debug email threading by showing the Message-ID chain."""
        if email_id not in self.emails:
            return f"Email {email_id} not found"
        
        chain = []
        current_id = email_id
        
        while current_id and current_id in self.emails:
            email = self.emails[current_id]
            chain.append(f"ID: {current_id}, Message-ID: {email.message_id}, Reply-To: {email.reply_to_id}")
            current_id = email.reply_to_id
        
        return "Email Thread Chain:\n" + "\n".join(chain)
    
    def start_monitoring(self):
        """Start monitoring for incoming emails."""
        if self.monitoring:
            return
        
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_inbox, daemon=True)
        self.monitor_thread.start()
        logger.info("Started email monitoring thread")
    
    def stop_monitoring(self):
        """Stop monitoring for incoming emails."""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join()
        logger.info("Stopped email monitoring")
    
    def _monitor_inbox(self):
        """Monitor Gmail inbox for incoming emails."""
        while self.monitoring:
            try:
                if self.auth_method in ["oauth2_service_account", "oauth2_user_consent"]:
                    self._check_inbox_oauth2()
                else:
                    self._check_inbox_imap()
                time.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Error in inbox monitoring: {e}")
                time.sleep(60)  # Wait longer on error
    
    def _check_inbox_oauth2(self):
        """Check Gmail inbox using OAuth 2.0 and Gmail API."""
        try:
            if not self.gmail_service:
                return
            
            # Get unread messages
            results = self.gmail_service.users().messages().list(
                userId='me', labelIds=['UNREAD']
            ).execute()
            
            messages = results.get('messages', [])
            logger.info(f"Found {len(messages)} unread messages in Gmail inbox")
            
            for message in messages:
                try:
                    # Get full message details
                    msg = self.gmail_service.users().messages().get(
                        userId='me', id=message['id']
                    ).execute()
                    
                    logger.info(f"Processing message {message['id']}")
                    
                    # Check if this is a reply to a Meshtastic email
                    if self._is_meshtastic_reply_api(msg):
                        logger.info(f"Message {message['id']} identified as Meshtastic reply")
                        self._process_incoming_reply_api(msg)
                    else:
                        logger.info(f"Message {message['id']} not identified as Meshtastic reply")
                    
                    # Mark as read
                    self.gmail_service.users().messages().modify(
                        userId='me', id=message['id'],
                        body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                    
                except Exception as e:
                    logger.error(f"Error processing message {message['id']}: {e}")
                    
        except Exception as e:
            logger.error(f"Error checking inbox via OAuth 2.0: {e}")
    
    def _check_inbox_imap(self):
        """Check Gmail inbox using IMAP."""
        try:
            with self._get_imap_connection() as imap:
                imap.select('INBOX')
                
                # Search for unread emails
                _, message_numbers = imap.search(None, 'UNSEEN')
                
                for num in message_numbers[0].split():
                    try:
                        _, msg_data = imap.fetch(num, '(RFC822)')
                        email_body = msg_data[0][1]
                        email_message = email.message_from_bytes(email_body)
                        
                        # Check if this is a reply to a Meshtastic email
                        if self._is_meshtastic_reply(email_message):
                            self._process_incoming_reply(email_message)
                        
                        # Mark as read
                        imap.store(num, '+FLAGS', '\\Seen')
                        
                    except Exception as e:
                        logger.error(f"Error processing email {num}: {e}")
                
        except Exception as e:
            logger.error(f"Error checking inbox via IMAP: {e}")
    
    def _is_meshtastic_reply(self, email_message) -> bool:
        """Check if an email is a reply to a Meshtastic email (IMAP)."""
        # Check for Meshtastic headers
        if email_message.get('X-Meshtastic-Email-ID'):
            return True
        
        # Check if it's a reply to our bot email
        if email_message.get('To') == self.gmail_email:
            return True
        
        return False
    
    def _is_meshtastic_reply_api(self, message_data) -> bool:
        """Check if an email is a reply to a Meshtastic email (Gmail API)."""
        headers = message_data.get('payload', {}).get('headers', [])
        
        logger.info(f"Checking if message is Meshtastic reply. Found {len(headers)} headers")
        
        # Check for Meshtastic-specific headers (most reliable)
        for header in headers:
            if header['name'] == 'X-Meshtastic-Email-ID':
                logger.info(f"Found X-Meshtastic-Email-ID header: {header['value']}")
                return True
        
        # Check if it's a reply to any email (has In-Reply-To header)
        for header in headers:
            if header['name'] == 'In-Reply-To':
                logger.info(f"Found In-Reply-To header: {header['value']}")
                return True
        
        # Check if it's a reply to any email (has References header)
        for header in headers:
            if header['name'] == 'References':
                logger.info(f"Found References header: {header['value']}")
                return True
        
        # Only consider it a reply if it's sent to our bot AND has a subject that suggests it's a reply
        # This filters out system emails, delivery notifications, etc.
        to_header = None
        subject_header = None
        from_header = None
        
        for header in headers:
            if header['name'] == 'To':
                to_header = header['value']
            elif header['name'] == 'Subject':
                subject_header = header['value']
            elif header['name'] == 'From':
                from_header = header['value']
        
        # Must be sent to our bot AND have a subject that suggests it's a user reply
        # AND not be from a system email address
        logger.info(f"Fallback check - To: {to_header}, Subject: {subject_header}, From: {from_header}")
        
        if (to_header == self.gmail_email and 
            subject_header and 
            from_header and
            not any(system_indicator in subject_header.lower() for system_indicator in [
                'delivery', 'bounce', 'failure', 'notification', 'security', 'verification',
                'welcome', 'setup', 'account', 'google', 'gmail', 'no-reply', 'noreply'
            ]) and
            not any(system_indicator in from_header.lower() for system_indicator in [
                'no-reply', 'noreply', 'mailer-daemon', 'postmaster', 'google', 'gmail'
            ])):
            logger.info("Message passed fallback checks - treating as Meshtastic reply")
            return True
        
        logger.info("Message failed fallback checks - not a Meshtastic reply")
        return False
    
    def _process_incoming_reply(self, email_message):
        """Process an incoming reply email (IMAP)."""
        try:
            # Extract email details
            sender_email = email_message.get('From', '')
            subject = email_message.get('Subject', '')
            
            # Decode subject if needed
            if subject:
                decoded_subject = decode_header(subject)[0][0]
                if isinstance(decoded_subject, bytes):
                    subject = decoded_subject.decode('utf-8', errors='ignore')
                else:
                    subject = str(decoded_subject)
            
            # Extract body
            body = ""
            if email_message.is_multipart():
                for part in email_message.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        break
            else:
                body = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')
            
            # Try to find the original Meshtastic email ID
            original_email_id = None
            if email_message.get('X-Meshtastic-Email-ID'):
                original_email_id = email_message.get('X-Meshtastic-Email-ID')
            
            # Extract Message-ID for threading
            gmail_message_id = email_message.get('Message-ID')
            
            self._store_incoming_reply(sender_email, subject, body, original_email_id, gmail_message_id)
            
        except Exception as e:
            logger.error(f"Error processing incoming reply: {e}")
    
    def _process_incoming_reply_api(self, message_data):
        """Process an incoming reply email (Gmail API)."""
        try:
            headers = message_data.get('payload', {}).get('headers', [])
            sender_email = ""
            subject = ""
            
            # Extract headers
            for header in headers:
                if header['name'] == 'From':
                    sender_email = header['value']
                    # Extract clean email address from "Display Name <email@domain.com>" format
                    if '<' in sender_email and '>' in sender_email:
                        sender_email = sender_email.split('<')[1].split('>')[0]
                elif header['name'] == 'Subject':
                    subject = header['value']
            
            # Extract body
            body = self._extract_body_from_gmail_api(message_data)
            
            # Extract Gmail Message-ID for proper threading
            gmail_message_id = None
            for header in headers:
                if header['name'] == 'Message-ID':
                    gmail_message_id = header['value']
                    break
            
            # Log all headers for debugging
            logger.info(f"Processing email from {sender_email} with subject: {subject}")
            logger.info("All headers found:")
            for header in headers:
                logger.info(f"  {header['name']}: {header['value']}")
            
            # Try to find the original Meshtastic email ID
            original_email_id = None
            
            # First check for Meshtastic-specific header
            for header in headers:
                if header['name'] == 'X-Meshtastic-Email-ID':
                    original_email_id = header['value']
                    logger.info(f"Found X-Meshtastic-Email-ID: {original_email_id}")
                    break
            
            # If not found, check In-Reply-To header
            if not original_email_id:
                for header in headers:
                    if header['name'] == 'In-Reply-To':
                        # Extract the message ID from In-Reply-To
                        message_id = header['value']
                        logger.info(f"Found In-Reply-To: {message_id}")
                        # Gmail message IDs are not useful for finding our emails
                        # Skip this and try subject matching instead
                        logger.info("In-Reply-To contains Gmail message ID, will try subject matching")
                        break
            
            # If still not found, check References header
            if not original_email_id:
                for header in headers:
                    if header['name'] == 'References':
                        # Extract the first message ID from References
                        references = header['value']
                        if references:
                            message_id = references.split()[0]  # First reference
                            logger.info(f"Found References: {message_id}")
                            # Gmail message IDs are not useful for finding our emails
                            # Skip this and try subject matching instead
                            logger.info("References contains Gmail message ID, will try subject matching")
                        break
            
            # If still not found, try to match by subject (for replies that don't preserve headers)
            if not original_email_id and subject:
                logger.info(f"Trying to match by subject: '{subject}'")
                # Look for emails with similar subjects (common in email clients)
                for email_id, email_msg in self.emails.items():
                    if email_msg.direction == 'outgoing':
                        logger.info(f"Checking outgoing email {email_id}: subject='{email_msg.subject}', recipient='{email_msg.recipient_email}'")
                        
                        # Check if this is a reply to our email
                        logger.info(f"Comparing: recipient='{email_msg.recipient_email}' vs sender='{sender_email}'")
                        logger.info(f"Comparing: subject='{email_msg.subject}' vs reply_subject='{subject}'")
                        
                        # Check if this is a reply to our email
                        # Remove "Re:" prefix and compare subjects
                        clean_reply_subject = subject.lower().replace('re:', '').strip()
                        clean_original_subject = email_msg.subject.lower()
                        
                        if (email_msg.recipient_email == sender_email and
                            (clean_reply_subject == clean_original_subject or
                             clean_original_subject in clean_reply_subject)):
                            logger.info(f"Matched reply by subject similarity to email {email_id}")
                            logger.info(f"  Original: '{clean_original_subject}'")
                            logger.info(f"  Reply: '{clean_reply_subject}'")
                            original_email_id = email_id
                            break
                
                if not original_email_id:
                    logger.warning(f"Subject matching failed - no outgoing email found for {sender_email} with subject similar to '{subject}'")
            
            if not original_email_id:
                logger.warning("No reply headers found - this might not be a reply to a Meshtastic email")
            
            self._store_incoming_reply(sender_email, subject, body, original_email_id, gmail_message_id)
            
        except Exception as e:
            logger.error(f"Error processing incoming reply via API: {e}")
    
    def _extract_body_from_gmail_api(self, message_data):
        """Extract email body from Gmail API message data."""
        try:
            payload = message_data.get('payload', {})
            
            if 'parts' in payload:
                # Multipart message
                for part in payload['parts']:
                    if part.get('mimeType') == 'text/plain':
                        data = part.get('body', {}).get('data', '')
                        if data:
                            import base64
                            return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            else:
                # Simple message
                data = payload.get('body', {}).get('data', '')
                if data:
                    import base64
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
            
            return ""
        except Exception as e:
            logger.error(f"Error extracting body from Gmail API: {e}")
            return ""
    
    def _store_incoming_reply(self, sender_email: str, subject: str, body: str, original_email_id: str, gmail_message_id: str = None):
        """Store incoming reply email."""
        try:
            # Create unique ID for this reply
            unique_id = self._generate_short_id()
            
            # Store the incoming email with actual Gmail Message-ID if available
            email_msg = EmailMessage(
                unique_id=unique_id,
                sender_meshtastic_id=0,  # Will be set when we know the recipient
                sender_email=sender_email,
                recipient_email=self.gmail_email,
                subject=subject,
                body=body,
                timestamp=time.time(),
                direction='incoming',
                reply_to_id=original_email_id,
                message_id=gmail_message_id or f"<{unique_id}@meshtastic.local>"
            )
            self.emails[unique_id] = email_msg
            self._save_emails()
            
            logger.info(f"Processed incoming reply email with ID: {unique_id}")
            
        except Exception as e:
            logger.error(f"Error storing incoming reply: {e}")
    
    def get_pending_replies(self) -> List[EmailMessage]:
        """Get all incoming emails that need to be relayed back to Meshtastic users."""
        # Filter out system emails and only return actual user replies
        valid_replies = []
        for email_msg in self.emails.values():
            if (email_msg.direction == 'incoming' and 
                email_msg.sender_meshtastic_id == 0 and
                email_msg.reply_to_id):
                valid_replies.append(email_msg)
        
        # If we find replies without valid reply_to_id, mark them as processed to clean them up
        for email_msg in self.emails.values():
            if (email_msg.direction == 'incoming' and 
                email_msg.sender_meshtastic_id == 0 and
                not email_msg.reply_to_id):
                logger.info(f"Marking system email {email_msg.unique_id} as processed (not a valid reply)")
                email_msg.sender_meshtastic_id = -1  # Mark as processed but invalid
                self._save_emails()
        
        return valid_replies
    
    def mark_reply_processed(self, email_id: str, meshtastic_user_id: int):
        """Mark a reply as processed and associate it with a Meshtastic user."""
        if email_id in self.emails:
            self.emails[email_id].sender_meshtastic_id = meshtastic_user_id
            self._save_emails()
    
    def cleanup_old_emails(self, max_age_days: int = 30):
        """Clean up old emails to prevent storage bloat."""
        cutoff_time = time.time() - (max_age_days * 24 * 3600)
        old_emails = [email_id for email_id, email_msg in self.emails.items() 
                     if email_msg.timestamp < cutoff_time]
        
        for email_id in old_emails:
            del self.emails[email_id]
        
        if old_emails:
            self._save_emails()
            logger.info(f"Cleaned up {len(old_emails)} old emails")
