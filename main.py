#!/usr/bin/env python3
"""
Meshtastic AI DM Bot - Main Entry Point

Public rule: /bot, /help and /weather in public -> nudge only.
All AI and weather flows happen in DM with the bot.
"""

import asyncio
import json
import logging
import os
import time
import threading
from typing import Optional, Set, Dict
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

from protobuf_parser import ProtobufParser
from session_manager import SessionManager
from ai_handler import AIHandler
from response_chunker import ResponseChunker
from weather_handler import WeatherHandler
from email_handler import EmailHandler

# --- setup ---

load_dotenv("config.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

KNOWN_SENDERS_FILE = os.getenv("KNOWN_SENDERS_FILE", "known_senders.json")


def node_hex_to_decimal(hex_with_bang: str) -> Optional[int]:
    try:
        if not hex_with_bang or not hex_with_bang.startswith('!'):
            return None
        return int(hex_with_bang[1:], 16)
    except Exception:
        return None


class MeshtasticAIBot:
    def __init__(self):
        # MQTT
        self.mqtt_host = os.getenv("MQTT_HOST", "localhost")
        self.mqtt_port = int(os.getenv("MQTT_PORT", 1883))
        self.mqtt_user = os.getenv("MQTT_USER")
        self.mqtt_pass = os.getenv("MQTT_PASS")
        self.root_filter = os.getenv("ROOT_FILTER", "msh/#")

        # Response
        self.chunk_bytes = int(os.getenv("CHUNK_BYTES", 180))
        self.chunk_delay = float(os.getenv("CHUNK_DELAY_SECONDS", 1.2))

        # Mesh
        self.default_region = os.getenv("DEFAULT_REGION", "EU")
        self.default_version = os.getenv("DEFAULT_VERSION", "2")
        self.default_channel_index = int(os.getenv("DEFAULT_CHANNEL_INDEX", 0))  # fallback

        # AI
        self.ai_backend = os.getenv("AI_BACKEND", "gemini")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        
        # Email
        self.gmail_email = os.getenv("GMAIL_EMAIL", "meshtasticbot@gmail.com")
        self.gmail_auth_method = os.getenv("GMAIL_AUTH_METHOD", "app_password")
        self.gmail_auth_credentials = os.getenv("GMAIL_AUTH_CREDENTIALS")

        # State
        self.mqtt_client: Optional[mqtt.Client] = None
        self.known_senders: Set[str] = set()
        self.gateway_channel_index: Dict[str, int] = {}

        # components
        self.protobuf_parser = ProtobufParser()
        self.session_manager = SessionManager()
        self.weather = WeatherHandler()
        if self.ai_backend == "gemini" and self.gemini_api_key:
            self.ai_handler = AIHandler(self.gemini_api_key)
        else:
            raise ValueError("Gemini API key required")
        
        # Initialize email handler with appropriate authentication
        if self.gmail_auth_method == "oauth2_service_account":
            # For OAuth2 service account, credentials should be path to JSON file or JSON string
            if self.gmail_auth_credentials and os.path.exists(self.gmail_auth_credentials):
                # File path provided
                auth_creds = self.gmail_auth_credentials
            elif self.gmail_auth_credentials:
                # JSON string provided
                try:
                    auth_creds = json.loads(self.gmail_auth_credentials)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in GMAIL_AUTH_CREDENTIALS")
                    auth_creds = None
            else:
                auth_creds = None
        elif self.gmail_auth_method == "oauth2_user_consent":
            # For OAuth2 user consent, credentials should be path to token.json file
            if self.gmail_auth_credentials and os.path.exists(self.gmail_auth_credentials):
                auth_creds = self.gmail_auth_credentials
            else:
                logger.error(f"Token file not found: {self.gmail_auth_credentials}")
                auth_creds = None
        else:
            # For app password, use the credentials directly
            auth_creds = self.gmail_auth_credentials
        
        if auth_creds:
            self.email_handler = EmailHandler(
                gmail_email=self.gmail_email,
                auth_method=self.gmail_auth_method,
                auth_credentials=auth_creds
            )
        else:
            logger.warning("Email handler not initialized - missing credentials")
            self.email_handler = None

        self.response_chunker = ResponseChunker(self.chunk_bytes)
        self._load_known_senders()

    # ---------- persistence of known DM users ----------

    def _load_known_senders(self):
        try:
            if os.path.exists(KNOWN_SENDERS_FILE):
                with open(KNOWN_SENDERS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.known_senders = set(str(x) for x in data)
            logger.info(f"Loaded {len(self.known_senders)} known sender(s).")
        except Exception as e:
            logger.warning(f"Could not load known senders file: {e}")

    def _save_known_senders(self):
        try:
            with open(KNOWN_SENDERS_FILE, "w", encoding="utf-8") as f:
                json.dump(sorted(self.known_senders), f)
        except Exception as e:
            logger.warning(f"Could not save known senders file: {e}")

    def _mark_known(self, sender_num: int):
        s = str(sender_num)
        if s not in self.known_senders:
            self.known_senders.add(s)
            self._save_known_senders()

    # ---------- mqtt/json helpers ----------

    @staticmethod
    def _topic_tail_nodeid(topic: str) -> Optional[str]:
        for token in reversed(topic.split('/')):
            if token.startswith('!') and len(token) > 1:
                return token
        return None

    @staticmethod
    def _json_extract_text(parsed: dict) -> Optional[str]:
        if not isinstance(parsed, dict):
            return None
        payload = parsed.get("payload")
        if isinstance(payload, dict):
            if isinstance(payload.get("text"), str):
                return payload["text"]
            decoded = payload.get("decoded")
            if isinstance(decoded, dict) and isinstance(decoded.get("text"), str):
                return decoded["text"]
        if isinstance(parsed.get("text"), str):
            return parsed["text"]
        return None

    @staticmethod
    def _json_is_public(parsed: dict) -> bool:
        to_field = parsed.get("to")
        if to_field is None:
            return True
        if isinstance(to_field, str):
            return to_field.lower() in ("ffffffff", "0xffffffff")
        if isinstance(to_field, int):
            return to_field == 0xFFFFFFFF
        return True

    @staticmethod
    def _json_extract_channel_index(parsed: dict) -> Optional[int]:
        try:
            ch = parsed.get("channel")
            if isinstance(ch, int):
                return ch
            payload = parsed.get("payload")
            if isinstance(payload, dict):
                ch2 = payload.get("channel")
                if isinstance(ch2, int):
                    return ch2
        except Exception:
            pass
        return None

    # ---------- publish to json/mqtt ----------

    def _json_mqtt_topic(self) -> str:
        return f"msh/{self.default_region}/{self.default_version}/json/mqtt/"

    def _publish_json_mqtt(self, data: dict):
        topic = self._json_mqtt_topic()
        payload = json.dumps(data)
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.mqtt_client.publish(topic, payload)
            logger.info(f"Published json/mqtt: {topic} -> {payload}")
        else:
            logger.warning("MQTT client not connected, cannot publish downlink")

    def _channel_index_for_gateway(self, gateway_hex: str) -> int:
        return self.gateway_channel_index.get(gateway_hex, self.default_channel_index)

    def _clean_email_body(self, body: str) -> str:
        """Clean email body by removing quoted text and email thread content."""
        if not body:
            return ""
        
        lines = body.split('\n')
        clean_lines = []
        
        for line in lines:
            # Skip lines that are typical email reply indicators
            if any(indicator in line.lower() for indicator in [
                'on ', ' wrote:', 'from:', 'sent:', 'to:', 'subject:', 
                'date:', 'message-id:', 'in-reply-to:', 'references:'
            ]):
                continue
            
            # Skip lines that start with '>' (quoted text)
            if line.strip().startswith('>'):
                continue
                
            # Stop processing when we hit the bot footer (keep content before it)
            if 'this message was forwarded from a bot on the meshtastic network' in line.lower():
                break
            
            # Keep the line if it's not empty and not just whitespace
            if line.strip():
                clean_lines.append(line)
        
        # Join and clean up extra whitespace
        result = '\n'.join(clean_lines).strip()
        
        # If we ended up with nothing meaningful, return the original body (truncated)
        if not result or len(result) < 5:
            # Return first 200 characters of original body as fallback
            fallback = body[:200].strip()
            if len(body) > 200:
                fallback += "..."
            return fallback
            
        return result

    def _generate_reply_subject(self, original_subject: str) -> str:
        """Generate a proper reply subject following email conventions."""
        if not original_subject:
            return "Re: Message"
        
        # Check if subject already starts with "Re: "
        if original_subject.lower().startswith("re: "):
            # Already a reply, don't add another "Re: "
            return original_subject
        else:
            # Add "Re: " prefix
            return f"Re: {original_subject}"

    def _send_dm(self, gateway_hex: str, dest_numeric: int, message: str):
        logger.info(f"Attempting to send DM via gateway {gateway_hex} to user {dest_numeric}")
        gw_dec = node_hex_to_decimal(gateway_hex)
        if gw_dec is None:
            logger.warning(f"Could not derive gateway decimal from {gateway_hex}; skipping DM.")
            return
        
        channel = self._channel_index_for_gateway(gateway_hex)
        logger.info(f"Gateway {gateway_hex} -> decimal: {gw_dec}, channel: {channel}")
        
        data = {
            "from": gw_dec,
            "to": dest_numeric,
            "channel": channel,
            "type": "sendtext",
            "payload": message
        }
        logger.info(f"Sending DM data: {data}")
        self._publish_json_mqtt(data)

    def _send_public_nudge(self, gateway_hex: str, text: str):
        gw_dec = node_hex_to_decimal(gateway_hex)
        if gw_dec is None:
            return
        data = {
            "from": gw_dec,
            "to": 0xFFFFFFFF,
            "channel": self._channel_index_for_gateway(gateway_hex),
            "type": "sendtext",
            "payload": text
        }
        self._publish_json_mqtt(data)

    def _request_gps_from_user(self, gateway_hex: str, dest_numeric: int):
        gw_dec = node_hex_to_decimal(gateway_hex)
        if gw_dec is None:
            return
        data = {
            "from": gw_dec,
            "to": dest_numeric,
            "channel": self._channel_index_for_gateway(gateway_hex),
            "type": "requestposition",
            "payload": ""
        }
        self._publish_json_mqtt(data)

    # ---------- help text ----------

    def _send_help(self, gateway_hex: str, user_id: int):
        logger.info(f"Sending help to user {user_id} via gateway {gateway_hex}")
        help_lines = [
            "/ai <question> — ask the AI (context-aware).",
            "/weather — try GPS, then ask for a typed location.",
            "/weather <lat,lon> — override with coordinates.",
            "/weather <City[, Country]> — override with place name.",
            "/weather clear — forget cached location.",
            "/email <email> <subject> — send an email.",
            "/email get <id> — view email details.",
            "/email thread <id> — view complete email conversation.",
            "/email reply <id> — reply to an email (subject auto-generated).",
            "/email debug <id> — debug email threading information.",
            "/bot — brief intro and tips.",
        ]
        # Use the exact same logic as weather responses: format string with \n + join
        help_text = "Commands:\n{}".format("\n".join(help_lines))
        logger.info(f"Help text prepared: {len(help_text)} characters")
        # Use chunked response for help text (same as AI responses)
        self._send_chunked_response(gateway_hex, user_id, help_text)
        logger.info(f"Help DM sent to user {user_id}")

    # ---------- weather flow (DM only) ----------

    def _handle_weather_dm(self, gateway_hex: str, user_id: int, arg_text: str):
        uid = str(user_id)
        self._mark_known(user_id)
        self.session_manager.create_session(uid)

        arg_text = (arg_text or "").strip()

        # Support explicit clear
        if arg_text.lower() == "clear":
            self.session_manager.clear_cached_location(uid)
            self._send_dm(gateway_hex, user_id, "Location cleared. Send /weather again (or provide a new location).")
            return

        # If user supplied a location override -> resolve + reply
        if arg_text:
            loc = self.weather.resolve_location(arg_text)
            if not loc:
                self._send_dm(gateway_hex, user_id, "Sorry, I couldn't parse that location. Try 'lat,lon' or 'City, Country'.")
                return
            lat, lon, label = loc
            self.session_manager.cache_location(uid, lat, lon, label)
            self._send_weather_reply(gateway_hex, user_id, lat, lon, label)
            self.session_manager.clear_pending_weather_request(uid)
            return

        # Use cached location if present
        cached = self.session_manager.get_cached_location(uid)
        if cached:
            lat, lon, label = cached
            self._send_weather_reply(gateway_hex, user_id, lat, lon, label)
            self.session_manager.clear_pending_weather_request(uid)
            return

        # Request GPS and set a reliable 20s fallback using threading.Timer
        self._send_dm(gateway_hex, user_id, "Requesting your node GPS… If it doesn't arrive in ~20s, I'll ask for a typed location.")
        self._request_gps_from_user(gateway_hex, user_id)
        self.session_manager.set_waiting_for_weather_location(uid, True, timeout_sec=20)

        def _fallback():
            if self.session_manager.has_pending_weather_request(uid):
                self.session_manager.clear_pending_weather_request(uid)
                self._send_dm(
                    gateway_hex, user_id,
                    "No GPS received. Please send a location (e.g. 'lat,lon' or 'City, Country')."
                )

        threading.Timer(20.0, _fallback).start()

    def _send_weather_reply(self, gateway_hex: str, user_id: int, lat: float, lon: float, label: str):
        hourly, daily = self.weather.fetch_forecast_lines(lat, lon)
        msg1 = "Weather for {}\nNext 6 hours:\n{}".format(label, "\n".join(hourly))
        msg2 = "Next 3 days:\n{}".format("\n".join(daily))
        self._send_dm(gateway_hex, user_id, msg1)
        self._send_dm(gateway_hex, user_id, msg2)

    def _maybe_handle_position_update(self, parsed: dict, gateway_hex: str):
        sender_num = parsed.get("from")
        if sender_num is None:
            return
        uid = str(sender_num)

        if not self.session_manager.has_pending_weather_request(uid):
            return

        def _norm(v):
            if isinstance(v, (int, float)):
                return float(v) / 1e7 if abs(v) > 1000 else float(v)
            return None

        def _find_coord(d: dict):
            lat = d.get("lat") or d.get("latitude") or d.get("latitudeI")
            lon = d.get("lon") or d.get("lng") or d.get("longitude") or d.get("longitudeI")
            if lat is not None and lon is not None:
                return _norm(lat), _norm(lon)
            payload = d.get("payload") or {}
            decoded = payload.get("decoded") if isinstance(payload, dict) else {}
            for src in (payload, decoded):
                if isinstance(src, dict):
                    la = src.get("lat") or src.get("latitude") or src.get("latitudeI")
                    lo = src.get("lon") or src.get("lng") or src.get("longitude") or src.get("longitudeI")
                    if la is not None and lo is not None:
                        return _norm(la), _norm(lo)
            return None

        coords = _find_coord(parsed)
        if not coords:
            return
        lat, lon = coords
        if lat is None or lon is None:
            return

        label = self.weather.reverse_label(lat, lon) or f"{lat:.4f},{lon:.4f}"
        self.session_manager.cache_location(uid, lat, lon, label)
        self.session_manager.clear_pending_weather_request(uid)
        self._send_weather_reply(gateway_hex, sender_num, lat, lon, label)

    # ---------- Email flow (DM only) ----------

    def _handle_private_email(self, gateway_hex: str, sender_num: int, text: str):
        """Handle /email command in DM."""
        uid = str(sender_num)
        self._mark_known(sender_num)
        self.session_manager.create_session(uid)
        
        # Clear any existing email states
        self.session_manager.clear_all_email_states(uid)
        
        # Check if user provided parameters
        if not text.strip():
            self._send_dm(gateway_hex, sender_num, 
                         "Email syntax: /email <recipient_email> <subject>\n"
                         "Example: /email user@example.com Hello there")
            return
        
        # Parse the command - treat everything after the email address as the subject
        text = text.strip()
        if ' ' not in text:
            self._send_dm(gateway_hex, sender_num, 
                         "Email syntax: /email <recipient_email> <subject>\n"
                         "Example: /email user@example.com Hello there")
            return
        
        # Find the first space to separate email from subject
        first_space = text.find(' ')
        recipient_email = text[:first_space]
        subject = text[first_space + 1:]  # Everything after the first space
        
        # Validate email format (basic check)
        if '@' not in recipient_email or '.' not in recipient_email:
            self._send_dm(gateway_hex, sender_num, "Please provide a valid email address.")
            return
        
        # Store draft and wait for body
        draft_data = {
            'recipient_email': recipient_email,
            'subject': subject
        }
        self.session_manager.set_email_draft(uid, draft_data)
        self.session_manager.set_waiting_for_email_body(uid, True)
        
        self._send_dm(gateway_hex, sender_num, 
                     f"Email draft prepared:\nTo: {recipient_email}\nSubject: {subject}\n\nNow send me the email body content.")

    def _handle_email_body(self, gateway_hex: str, sender_num: int, body: str):
        """Handle email body input from user."""
        uid = str(sender_num)
        
        if not self.session_manager.is_waiting_for_email_body(uid):
            return False
        
        draft = self.session_manager.get_email_draft(uid)
        if not draft:
            self._send_dm(gateway_hex, sender_num, "No email draft found. Please start over with /email command.")
            return False
        
        # Send the email
        success, result = self.email_handler.send_email(
            sender_meshtastic_id=sender_num,
            sender_email=f"user_{sender_num}@meshtastic.local",
            recipient_email=draft['recipient_email'],
            subject=draft['subject'],
            body=body.strip(),
            reply_to_id=draft.get('reply_to_id')  # Pass reply_to_id if this is a reply
        )
        
        if success:
            self._send_dm(gateway_hex, sender_num, 
                         f"Email sent successfully!\nEmail ID: {result}\n\nYou can use /email get {result} to view this email later.")
        else:
            self._send_dm(gateway_hex, sender_num, f"Failed to send email: {result}")
        
        # Clear email states
        self.session_manager.clear_all_email_states(uid)
        return True

    def _handle_email_get(self, gateway_hex: str, sender_num: int, email_id: str):
        """Handle /email get command to retrieve email details."""
        uid = str(sender_num)
        self._mark_known(sender_num)
        self.session_manager.create_session(uid)
        
        email_msg = self.email_handler.get_email(email_id)
        if not email_msg:
            self._send_dm(gateway_hex, sender_num, f"Email with ID {email_id} not found.")
            return
        
        # Check if user has access to this email
        if email_msg.sender_meshtastic_id != sender_num:
            self._send_dm(gateway_hex, sender_num, "You don't have access to this email.")
            return
        
        # Format email details
        direction = "Sent" if email_msg.direction == 'outgoing' else "Received"
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(email_msg.timestamp))
        
        details = f"Email ID: {email_msg.unique_id}\n"
        details += f"Direction: {direction}\n"
        details += f"Timestamp: {timestamp}\n"
        details += f"From: {email_msg.sender_email}\n"
        details += f"To: {email_msg.recipient_email}\n"
        details += f"Subject: {email_msg.subject}\n"
        details += f"Body:\n{email_msg.body}"
        
        self._send_chunked_response(gateway_hex, sender_num, details)

    def _handle_email_thread(self, gateway_hex: str, sender_num: int, email_id: str):
        """Handle /email thread command to show complete email conversation."""
        uid = str(sender_num)
        self._mark_known(sender_num)
        self.session_manager.create_session(uid)
        
        email_msg = self.email_handler.get_email(email_id)
        if not email_msg:
            self._send_dm(gateway_hex, sender_num, f"Email with ID {email_id} not found.")
            return
        
        # Check if user has access to this email
        if email_msg.sender_meshtastic_id != sender_num:
            self._send_dm(gateway_hex, sender_num, "You don't have access to this email.")
            return
        
        # Get the complete thread
        thread = self.email_handler.get_email_thread(email_id)
        if not thread:
            self._send_dm(gateway_hex, sender_num, f"No thread found for email {email_id}")
            return
        
        # Send thread header
        self._send_dm(gateway_hex, sender_num, f"Email Thread for {email_id}:")
        
        # Send each email as a separate chunk for better readability
        for i, email in enumerate(thread, 1):
            direction = "→" if email.direction == 'outgoing' else "←"
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(email.timestamp))
            
            email_details = f"{i}. {direction} {email.unique_id} - {email.subject}\n"
            email_details += f"   From: {email.sender_email}\n"
            email_details += f"   To: {email.recipient_email}\n"
            email_details += f"   Time: {timestamp}"
            
            # Send each email as its own chunk
            self._send_chunked_response(gateway_hex, sender_num, email_details)

    def _handle_email_debug(self, gateway_hex: str, sender_num: int, email_id: str):
        """Handle /email debug command to show email threading information."""
        uid = str(sender_num)
        self._mark_known(sender_num)
        self.session_manager.create_session(uid)
        
        email_msg = self.email_handler.get_email(email_id)
        if not email_msg:
            self._send_dm(gateway_hex, sender_num, f"Email with ID {email_id} not found.")
            return
        
        # Check if user has access to this email
        if email_msg.sender_meshtastic_id != sender_num:
            self._send_dm(gateway_hex, sender_num, "You don't have access to this email.")
            return
        
        # Get debug information
        debug_info = self.email_handler.debug_email_threading(email_id)
        self._send_dm(gateway_hex, sender_num, debug_info)

    def _handle_email_reply(self, gateway_hex: str, sender_num: int, text: str):
        """Handle /email reply command."""
        uid = str(sender_num)
        self._mark_known(sender_num)
        self.session_manager.create_session(uid)
        
        # Clear any existing email states
        self.session_manager.clear_all_email_states(uid)
        
        # Parse the command - just need email ID
        email_id = text.strip()
        if not email_id:
            self._send_dm(gateway_hex, sender_num, 
                         "Reply syntax: /email reply <email_id>\n"
                         "Example: /email reply abc123")
            return
        
        # Get the original email
        original_email = self.email_handler.get_email(email_id)
        if not original_email:
            self._send_dm(gateway_hex, sender_num, f"Email with ID {email_id} not found.")
            return
        
        # Check if user has access to this email
        if original_email.sender_meshtastic_id != sender_num:
            self._send_dm(gateway_hex, sender_num, "You don't have access to this email.")
            return
        
        # Automatically generate the reply subject
        reply_subject = self._generate_reply_subject(original_email.subject)
        
        # Store draft and wait for body
        draft_data = {
            'recipient_email': original_email.sender_email,
            'subject': reply_subject,
            'reply_to_id': email_id
        }
        self.session_manager.set_email_draft(uid, draft_data)
        self.session_manager.set_waiting_for_email_body(uid, True)
        
        self._send_dm(gateway_hex, sender_num, 
                     f"Reply email draft prepared:\nTo: {original_email.sender_email}\nSubject: {reply_subject}\n\nNow send me the reply body content.")

    def _check_pending_email_replies(self, gateway_hex: str):
        """Check for pending email replies and relay them to users."""
        if not hasattr(self, 'email_handler') or not self.email_handler:
            logger.warning("Email handler not available for checking pending replies")
            return
            
        pending_replies = self.email_handler.get_pending_replies()
        logger.info(f"Checking for pending email replies: found {len(pending_replies)}")
        
        for reply in pending_replies:
            logger.info(f"Processing reply {reply.unique_id} from {reply.sender_email}")
            
            # Try to find the original email to determine recipient
            if reply.reply_to_id:
                logger.info(f"Reply has reply_to_id: {reply.reply_to_id}")
                original_email = self.email_handler.get_email(reply.reply_to_id)
                if original_email:
                    logger.info(f"Found original email {reply.reply_to_id}, sending to user {original_email.sender_meshtastic_id}")
                    # Relay the reply to the original sender using chunked response (same as AI responses)
                    # Clean the email body to remove quoted text and save on Meshtastic traffic
                    clean_body = self._clean_email_body(reply.body)
                    
                    # Format with essential info only (using plain text to avoid encoding issues)
                    reply_message = f"Email Reply Received\nFrom: {reply.sender_email}\nSubject: {reply.subject}\n\n{clean_body}\n\nEmail ID: {reply.unique_id}"
                    
                    # Use the same chunked response logic that works for AI responses
                    self._send_chunked_response(gateway_hex, original_email.sender_meshtastic_id, reply_message)
                    
                    # Mark as processed
                    self.email_handler.mark_reply_processed(reply.unique_id, original_email.sender_meshtastic_id)
                    logger.info(f"Reply {reply.unique_id} forwarded and marked as processed")
                else:
                    logger.warning(f"Could not find original email with ID: {reply.reply_to_id}")
            else:
                logger.warning(f"Reply {reply.unique_id} has no reply_to_id, cannot determine recipient")

    # ---------- AI flow (DM only) ----------

    def _handle_private_bot(self, gateway_hex: str, sender_num: int):
        self._mark_known(sender_num)
        self.session_manager.create_session(str(sender_num))
        self._send_dm(gateway_hex, sender_num, "Hi! I'm your Gemini bot. Use /ai <question>, /weather, or /email commands. (/weather clear for new weather request)")

    def _handle_private_ai(self, gateway_hex: str, sender_num: int, text: str):
        if not text.strip():
            self._send_dm(gateway_hex, sender_num, "Send /ai followed by your question.")
            return
        self._mark_known(sender_num)
        self.session_manager.create_session(str(sender_num))
        try:
            resp = self.ai_handler.chat_respond(str(sender_num), text.strip())
            self._send_chunked_response(gateway_hex, sender_num, resp)
        except Exception as e:
            self._send_dm(gateway_hex, sender_num, f"AI request failed: {e}")

    # ---------- public nudges ----------

    def _handle_public_bot(self, gateway_hex: str):
        self._send_public_nudge(gateway_hex, "Please DM me and use /ai, /weather, or /email there. For help: send /help in DM.")

    def _handle_public_weather(self, gateway_hex: str):
        self._send_public_nudge(gateway_hex, "Please DM me and send /weather (optionally add 'lat,lon' or 'City, Country').")

    def _handle_public_help(self, gateway_hex: str):
        self._send_public_nudge(gateway_hex, "Help is available via DM. Send /help to me in a private message.")
    
    def _handle_public_email(self, gateway_hex: str):
        self._send_public_nudge(gateway_hex, "Please DM me and send /email <recipient_email> <subject> to send an email. Use /email reply <id> to maintain email threads.")

    # ---------- chunked sender ----------

    def _send_chunked_response(self, gateway_hex: str, dest_numeric: int, response: str):
        chunks = self.response_chunker.chunk_text(response)

        async def _send():
            for i, chunk in enumerate(chunks):
                self._send_dm(gateway_hex, dest_numeric, chunk)
                if i < len(chunks) - 1:
                    await asyncio.sleep(self.chunk_delay)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_send())
        except RuntimeError:
            asyncio.run(_send())

    # ---------- MQTT callbacks ----------

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
        else:
            logger.error(f"MQTT connection failed with code: {rc}")
            return
        client.subscribe(self.root_filter)
        logger.info(f"Subscribed to: {self.root_filter}")

    def _on_message(self, client, userdata, msg):
        try:
            parsed = None
            try:
                parsed = json.loads(msg.payload.decode("utf-8"))
            except Exception:
                parsed = None

            if isinstance(parsed, dict):
                text = self._json_extract_text(parsed)
                gateway_hex = self._topic_tail_nodeid(msg.topic) or ""
                sender_num = parsed.get("from")
                is_public = self._json_is_public(parsed)

                learned_ch = self._json_extract_channel_index(parsed)
                if learned_ch is not None and gateway_hex:
                    prev = self.gateway_channel_index.get(gateway_hex)
                    self.gateway_channel_index[gateway_hex] = learned_ch
                    if prev != learned_ch:
                        logger.info(f"Gateway {gateway_hex}: learned channel index {learned_ch}")

                # If GPS position arrives while we are waiting, handle immediately (reply by DM)
                self._maybe_handle_position_update(parsed, gateway_hex)

                if not text:
                    return

                low = text.lower().strip()
                logger.info(f"Processing message: text='{text}', low='{low}', is_public={is_public}, sender_num={sender_num}")

                # PUBLIC: nudge only
                if is_public and "/bot" in low:
                    self._handle_public_bot(gateway_hex)
                    return
                if is_public and low.startswith("/weather"):
                    self._handle_public_weather(gateway_hex)
                    return
                if is_public and low.startswith("/ai"):
                    self._handle_public_bot(gateway_hex)
                    return
                if is_public and low.startswith("/help"):
                    self._handle_public_help(gateway_hex)
                    return
                if is_public and low.startswith("/email"):
                    self._handle_public_email(gateway_hex)
                    return

                # PRIVATE: real work
                if not is_public and "/bot" in low:
                    if sender_num is not None:
                        self._handle_private_bot(gateway_hex, sender_num)
                    return

                if not is_public and low.startswith("/help"):
                    logger.info(f"Help command detected in DM from {sender_num}")
                    if sender_num is not None:
                        self._send_help(gateway_hex, sender_num)
                        logger.info(f"Help sent to user {sender_num}")
                    else:
                        logger.warning("Help command but no sender_num")
                    return

                if not is_public and low.startswith("/ai"):
                    if sender_num is not None:
                        self._handle_private_ai(gateway_hex, sender_num, text[3:].strip())
                    return

                if not is_public and low.startswith("/weather"):
                    if sender_num is not None:
                        args = text[len("/weather"):].strip()
                        self._handle_weather_dm(gateway_hex, sender_num, args)
                    return

                # Check for specific email subcommands FIRST (before the general /email command)
                if not is_public and low.startswith("/email get"):
                    if sender_num is not None:
                        args = text[len("/email get"):].strip()
                        if args:
                            self._handle_email_get(gateway_hex, sender_num, args)
                        else:
                            self._send_dm(gateway_hex, sender_num, "Please provide an email ID: /email get <email_id>")
                    return

                if not is_public and low.startswith("/email thread"):
                    if sender_num is not None:
                        args = text[len("/email thread"):].strip()
                        if args:
                            self._handle_email_thread(gateway_hex, sender_num, args)
                        else:
                            self._send_dm(gateway_hex, sender_num, "Please provide an email ID: /email thread <email_id>")
                    return

                if not is_public and low.startswith("/email debug"):
                    if sender_num is not None:
                        args = text[len("/email debug"):].strip()
                        if args:
                            self._handle_email_debug(gateway_hex, sender_num, args)
                        else:
                            self._send_dm(gateway_hex, sender_num, "Please provide an email ID: /email debug <email_id>")
                    return

                if not is_public and low.startswith("/email reply"):
                    if sender_num is not None:
                        args = text[len("/email reply"):].strip()
                        if args:
                            self._handle_email_reply(gateway_hex, sender_num, args)
                        else:
                            self._send_dm(gateway_hex, sender_num, "Please provide email ID: /email reply <email_id>")
                    return

                # General /email command (must come AFTER the specific subcommands)
                if not is_public and low.startswith("/email"):
                    if sender_num is not None:
                        args = text[len("/email"):].strip()
                        self._handle_private_email(gateway_hex, sender_num, args)
                    return

                # If we're waiting for a typed location (DM only), treat the next DM message as a location attempt
                if not is_public and sender_num is not None and self.session_manager.has_pending_weather_request(str(sender_num)):
                    attempt = text.strip()
                    loc = self.weather.resolve_location(attempt)
                    if not loc:
                        self._send_dm(gateway_hex, sender_num, "Sorry, I couldn't parse that location. Try 'lat,lon' or 'City, Country'.")
                        return
                    lat, lon, label = loc
                    self.session_manager.cache_location(str(sender_num), lat, lon, label)
                    self.session_manager.clear_pending_weather_request(str(sender_num))
                    self._send_weather_reply(gateway_hex, sender_num, lat, lon, label)
                    return

                # If we're waiting for an email body (DM only), treat the next DM message as email body
                if not is_public and sender_num is not None and self.session_manager.is_waiting_for_email_body(str(sender_num)):
                    if self._handle_email_body(gateway_hex, sender_num, text.strip()):
                        return

                return

            return

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"Disconnected from MQTT broker with code: {rc}")

    # ---------- lifecycle ----------

    def start(self):
        logger.info("Starting Meshtastic AI DM Bot...")
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message
        self.mqtt_client.on_disconnect = self._on_disconnect

        if self.mqtt_user and self.mqtt_pass:
            self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_pass)

        try:
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            logger.info(f"Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            return

        self.mqtt_client.loop_start()
        try:
            while True:
                # Check for pending email replies every 30 seconds
                if hasattr(self, 'email_handler'):
                    # Use the first available active gateway, or fall back to a default
                    active_gateway = None
                    if self.gateway_channel_index:
                        # Use the first available gateway
                        active_gateway = list(self.gateway_channel_index.keys())[0]
                        logger.info(f"Using active gateway: {active_gateway}")
                    else:
                        # Fall back to a default gateway (this should be updated based on actual usage)
                        active_gateway = "!1"
                        logger.warning(f"No active gateways found, using fallback: {active_gateway}")
                    
                    logger.info(f"Checking for pending email replies using gateway: {active_gateway}")
                    self._check_pending_email_replies(active_gateway)
                else:
                    logger.warning("Email handler not available in main loop")
                time.sleep(30)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        logger.info("Bot stopped")


def main():
    try:
        bot = MeshtasticAIBot()
        bot.start()
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
        raise


if __name__ == "__main__":
    main()
