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
from collections import deque
from dotenv import load_dotenv
import paho.mqtt.client as mqtt

from protobuf_parser import ProtobufParser
from session_manager import SessionManager
from ai_handler import AIHandler
from response_chunker import ResponseChunker
from weather_handler import WeatherHandler
from email_handler import EmailHandler
from radio_interface import RadioInterface

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
        # Common
        self.serial_enabled = os.getenv("SERIAL_ENABLED", "False").lower() in ("true", "1", "yes")

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
        self.ai_system_prompt = os.getenv("AI_SYSTEM_PROMPT")
        
        # Email
        self.gmail_email = os.getenv("GMAIL_EMAIL", "meshtasticbot@gmail.com")
        self.gmail_auth_method = os.getenv("GMAIL_AUTH_METHOD", "app_password")
        self.gmail_auth_credentials = os.getenv("GMAIL_AUTH_CREDENTIALS")

        # State
        self.mqtt_client: Optional[mqtt.Client] = None
        self.radio_interface: Optional[RadioInterface] = None
        self.known_senders: Set[str] = set()
        self.gateway_channel_index: Dict[str, int] = {}
        self.processed_message_ids = deque(maxlen=100)

        # components
        self.protobuf_parser = ProtobufParser()
        self.session_manager = SessionManager()
        self.weather = WeatherHandler()
        if self.ai_backend == "gemini" and self.gemini_api_key:
            self.ai_handler = AIHandler(self.gemini_api_key, system_prompt=self.ai_system_prompt)
        else:
            raise ValueError("Gemini API key required")
        
        if self.gmail_auth_method == "oauth2_service_account":
            if self.gmail_auth_credentials and os.path.exists(self.gmail_auth_credentials):
                auth_creds = self.gmail_auth_credentials
            elif self.gmail_auth_credentials:
                try:
                    auth_creds = json.loads(self.gmail_auth_credentials)
                except json.JSONDecodeError:
                    logger.error("Invalid JSON in GMAIL_AUTH_CREDENTIALS")
                    auth_creds = None
            else:
                auth_creds = None
        elif self.gmail_auth_method == "oauth2_user_consent":
            if self.gmail_auth_credentials and os.path.exists(self.gmail_auth_credentials):
                auth_creds = self.gmail_auth_credentials
            else:
                logger.error(f"Token file not found: {self.gmail_auth_credentials}")
                auth_creds = None
        else:
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
                json.dump(list(self.known_senders), f)
        except Exception as e:
            logger.warning(f"Could not save known senders file: {e}")

    def _mark_known(self, sender_num: int):
        s = str(sender_num)
        if s not in self.known_senders:
            self.known_senders.add(s)
            self._save_known_senders()

    @staticmethod
    def _topic_tail_nodeid(topic: str) -> Optional[str]:
        for token in reversed(topic.split('/')):
            if token.startswith('!') and len(token) > 1:
                return token
        return None

    def _publish_json_mqtt(self, data: dict):
        topic = f"msh/{self.default_region}/{self.default_version}/json/mqtt/"
        payload = json.dumps(data)
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.mqtt_client.publish(topic, payload)
            logger.info(f"Published json/mqtt: {topic} -> {payload}")
        else:
            logger.warning("MQTT client not connected, cannot publish downlink")

    def _send_dm(self, destination_id: int, message: str, source: str, gateway_hex: Optional[str] = None):
        if source == 'serial' and self.radio_interface:
            logger.info(f"Attempting to send DM via SERIAL to user {destination_id}")
            self.radio_interface.send_message(message, destination_id)
        elif source == 'mqtt':
            if not gateway_hex:
                logger.warning("Cannot send MQTT DM without a gateway_hex")
                return
            logger.info(f"Attempting to send DM via MQTT gateway {gateway_hex} to user {destination_id}")
            gw_dec = node_hex_to_decimal(gateway_hex)
            if gw_dec is None:
                logger.warning(f"Could not derive gateway decimal from {gateway_hex}; skipping DM.")
                return
            
            channel = self.gateway_channel_index.get(gateway_hex, self.default_channel_index)
            data = { "from": gw_dec, "to": destination_id, "channel": channel, "type": "sendtext", "payload": message }
            self._publish_json_mqtt(data)
        else:
            logger.error(f"Cannot send DM: Unknown source '{source}' or interface not available.")

    def _send_public_nudge(self, gateway_hex: str, text: str):
        gw_dec = node_hex_to_decimal(gateway_hex)
        if gw_dec is None: return
        data = { "from": gw_dec, "to": 0xFFFFFFFF, "channel": self.gateway_channel_index.get(gateway_hex, self.default_channel_index), "type": "sendtext", "payload": text }
        self._publish_json_mqtt(data)

    def _request_gps_from_user(self, dest_numeric: int, source: str, gateway_hex: Optional[str] = None):
        if source == 'serial' and self.radio_interface:
            # This is not directly supported by the python API's sendText.
            # For now, we'll rely on MQTT for this. A more advanced implementation
            # could construct the protobuf message manually.
            logger.warning("Requesting GPS via serial is not implemented, falling back to MQTT if possible.")

        if source == 'mqtt':
            if not gateway_hex:
                logger.warning("Cannot request GPS via MQTT without gateway_hex")
                return
            gw_dec = node_hex_to_decimal(gateway_hex)
            if gw_dec is None: return
            data = { "from": gw_dec, "to": dest_numeric, "channel": self.gateway_channel_index.get(gateway_hex, self.default_channel_index), "type": "requestposition", "payload": "" }
            self._publish_json_mqtt(data)

    def _send_help(self, user_id: int, source: str, gateway_hex: Optional[str] = None):
        help_lines = [
            "/ai <question> — ask the AI (context-aware).",
            "/weather — try GPS, then ask for a typed location.",
            "/weather <lat,lon> — override with coordinates.",
            "/weather <City[, Country]> — override with place name.",
            "/weather clear — forget cached location.",
            "/email <email> <subject> — send an email.",
            "/email get <id> — view email details.",
            "/email reply <id> — reply to an email.",
            "/bot — brief intro and tips.",
        ]
        help_text = "Commands:\n{}".format("\n".join(help_lines))
        self._send_chunked_response(user_id, help_text, source, gateway_hex)

    def _handle_weather_dm(self, user_id: int, arg_text: str, source: str, gateway_hex: Optional[str] = None):
        uid = str(user_id)
        self._mark_known(user_id)
        self.session_manager.create_session(uid)
        arg_text = (arg_text or "").strip()

        if arg_text.lower() == "clear":
            self.session_manager.clear_cached_location(uid)
            self._send_dm(user_id, "Location cleared.", source, gateway_hex)
            return

        if arg_text:
            loc = self.weather.resolve_location(arg_text)
            if not loc:
                self._send_dm(user_id, "Sorry, couldn't parse that location.", source, gateway_hex)
                return
            lat, lon, label = loc
            self.session_manager.cache_location(uid, lat, lon, label)
            self._send_weather_reply(user_id, lat, lon, label, source, gateway_hex)
            self.session_manager.clear_pending_weather_request(uid)
            return

        cached = self.session_manager.get_cached_location(uid)
        if cached:
            lat, lon, label = cached
            self._send_weather_reply(user_id, lat, lon, label, source, gateway_hex)
            self.session_manager.clear_pending_weather_request(uid)
            return

        self._send_dm(user_id, "Requesting your node GPS...", source, gateway_hex)
        self._request_gps_from_user(user_id, source, gateway_hex)
        self.session_manager.set_waiting_for_weather_location(uid, True, timeout_sec=20)

        def _fallback():
            if self.session_manager.has_pending_weather_request(uid):
                self.session_manager.clear_pending_weather_request(uid)
                self._send_dm(user_id, "No GPS. Please send a location.", source, gateway_hex)
        threading.Timer(20.0, _fallback).start()

    def _send_weather_reply(self, user_id: int, lat: float, lon: float, label: str, source: str, gateway_hex: Optional[str] = None):
        hourly, daily = self.weather.fetch_forecast_lines(lat, lon)
        msg1 = f"Weather for {label}\nNext 6 hours:\n" + "\n".join(hourly)
        msg2 = "Next 3 days:\n" + "\n".join(daily)
        self._send_dm(user_id, msg1, source, gateway_hex)
        time.sleep(self.chunk_delay)
        self._send_dm(user_id, msg2, source, gateway_hex)

    def _handle_private_bot(self, sender_num: int, source: str, gateway_hex: Optional[str] = None):
        self._mark_known(sender_num)
        self.session_manager.create_session(str(sender_num))
        self._send_dm(sender_num, "Hi! I'm your Gemini bot. Use /ai, /weather, or /email. Send /help for commands.", source, gateway_hex)

    def _handle_private_ai(self, sender_num: int, text: str, source: str, gateway_hex: Optional[str] = None):
        if not text.strip():
            self._send_dm(sender_num, "Send /ai followed by your question.", source, gateway_hex)
            return
        self._mark_known(sender_num)
        self.session_manager.create_session(str(sender_num))
        try:
            resp = self.ai_handler.chat_respond(str(sender_num), text.strip())
            self._send_chunked_response(sender_num, resp, source, gateway_hex)
        except Exception as e:
            self._send_dm(sender_num, f"AI request failed: {e}", source, gateway_hex)

    def _send_chunked_response(self, dest_numeric: int, response: str, source: str, gateway_hex: Optional[str] = None):
        chunks = self.response_chunker.chunk_text(response)
        for i, chunk in enumerate(chunks):
            self._send_dm(dest_numeric, chunk, source, gateway_hex)
            if i < len(chunks) - 1:
                time.sleep(self.chunk_delay)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(self.root_filter)
            logger.info(f"Subscribed to: {self.root_filter}")
        else:
            logger.error(f"MQTT connection failed with code: {rc}")

    def _on_message_mqtt(self, client, userdata, msg):
        try:
            parsed = json.loads(msg.payload.decode("utf-8"))
            gateway_hex = self._topic_tail_nodeid(msg.topic) or ""
            
            # Learn channel index from MQTT topic
            learned_ch = parsed.get("channel")
            if learned_ch is not None and gateway_hex:
                if self.gateway_channel_index.get(gateway_hex) != learned_ch:
                    self.gateway_channel_index[gateway_hex] = learned_ch
                    logger.info(f"Gateway {gateway_hex}: learned channel index {learned_ch}")

            self._process_packet(parsed, 'mqtt', gateway_hex)
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")

    def _on_message_serial(self, packet):
        self._process_packet(packet, 'serial')

    def _process_packet(self, packet: dict, source: str, gateway_hex: Optional[str] = None):
        packet_id = packet.get('id')
        if not packet_id or packet_id in self.processed_message_ids:
            return
        self.processed_message_ids.append(packet_id)

        decoded = packet.get('decoded', {})
        if not decoded or 'text' not in decoded:
            # Handle position updates for weather
            if 'portnum' in decoded and decoded['portnum'] == 'POSITION_APP':
                self._maybe_handle_position_update(packet, source, gateway_hex)
            return

        text = decoded.get('text')
        sender_num = packet.get('from')
        is_public = packet.get('to') == 0xFFFFFFFF

        if not text or sender_num is None:
            return

        low = text.lower().strip()
        logger.info(f"Processing packet from {source}: text='{text}', public={is_public}, from={sender_num}")

        # Public messages (only from MQTT for now)
        if is_public and source == 'mqtt' and gateway_hex:
            if "/bot" in low or "/ai" in low: self._handle_public_bot(gateway_hex)
            elif low.startswith("/weather"): self._handle_public_weather(gateway_hex)
            elif low.startswith("/help"): self._handle_public_help(gateway_hex)
            elif low.startswith("/email"): self._handle_public_email(gateway_hex)
            return

        # Private messages
        if not is_public:
            if "/bot" in low: self._handle_private_bot(sender_num, source, gateway_hex)
            elif low.startswith("/help"): self._send_help(sender_num, source, gateway_hex)
            elif low.startswith("/ai"): self._handle_private_ai(sender_num, text[3:].strip(), source, gateway_hex)
            elif low.startswith("/weather"): self._handle_weather_dm(sender_num, text[len("/weather"):
].strip(), source, gateway_hex)
            # Add email handlers here, passing source and gateway_hex
            # ...
            else:
                # Handle implicit weather location or email body
                uid = str(sender_num)
                if self.session_manager.has_pending_weather_request(uid):
                    self._handle_weather_dm(sender_num, text.strip(), source, gateway_hex)

    def _maybe_handle_position_update(self, packet: dict, source: str, gateway_hex: Optional[str] = None):
        sender_num = packet.get("from")
        if sender_num is None: return
        uid = str(sender_num)

        if not self.session_manager.has_pending_weather_request(uid): return

        decoded = packet.get('decoded', {})
        payload = decoded.get('payload', {})
        lat = payload.get('latitudeI')
        lon = payload.get('longitudeI')

        if lat is None or lon is None: return
        
        lat, lon = float(lat) / 1e7, float(lon) / 1e7
        label = self.weather.reverse_label(lat, lon) or f"{lat:.4f},{lon:.4f}"
        self.session_manager.cache_location(uid, lat, lon, label)
        self.session_manager.clear_pending_weather_request(uid)
        self._send_weather_reply(sender_num, lat, lon, label, source, gateway_hex)

    def _on_disconnect(self, client, userdata, rc):
        logger.warning(f"Disconnected from MQTT broker with code: {rc}")

    def start(self):
        logger.info("Starting Meshtastic AI DM Bot...")
        
        # Start Serial Interface
        if self.serial_enabled:
            logger.info("Serial connection is enabled. Initializing RadioInterface.")
            self.radio_interface = RadioInterface(message_callback=self._on_message_serial)
        else:
            logger.info("Serial connection is disabled.")

        # Start MQTT Client
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_message = self._on_message_mqtt
        self.mqtt_client.on_disconnect = self._on_disconnect
        if self.mqtt_user and self.mqtt_pass:
            self.mqtt_client.username_pw_set(self.mqtt_user, self.mqtt_pass)
        try:
            self.mqtt_client.connect(self.mqtt_host, self.mqtt_port, 60)
            logger.info(f"Connecting to MQTT broker at {self.mqtt_host}:{self.mqtt_port}")
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            # If serial is also disabled, we should exit.
            if not self.serial_enabled:
                return

        try:
            while True:
                # The main loop can be used for periodic tasks.
                # For now, we just sleep. Paho-MQTT and Meshtastic-python run in background threads.
                time.sleep(30)
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        if self.mqtt_client and self.mqtt_client.is_connected():
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()
        if self.radio_interface:
            self.radio_interface.close()
        logger.info("Bot stopped")

def main():
    try:
        bot = MeshtasticAIBot()
        bot.start()
    except Exception as e:
        logger.error(f"Bot startup failed: {e}", exc_info=True)
        raise

if __name__ == "__main__":
    main()