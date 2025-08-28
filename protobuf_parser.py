"""
Protobuf Parser for Meshtastic ServiceEnvelope messages.
This module handles the parsing of Meshtastic protobuf messages from MQTT.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Try to import Meshtastic protobufs; if unavailable, we'll fail gracefully.
try:
    from meshtastic.protobuf import mqtt_pb2, portnums_pb2  # type: ignore
    HAVE_PROTO = True
except Exception as e:
    logger.warning(f"Meshtastic protobufs not available: {e}")
    HAVE_PROTO = False


class ProtobufParser:
    """Parser for Meshtastic protobuf messages."""

    def __init__(self):
        # Fallback numeric for TEXT_MESSAGE_APP in case import above failed
        self.TEXT_MESSAGE_PORT = getattr(getattr(portnums_pb2, "PortNum", object()), "TEXT_MESSAGE_APP", 1)

    # -------- public API --------
    def parse_service_envelope(self, payload: bytes) -> Optional[Dict[str, Any]]:
        """
        Parse a Meshtastic ServiceEnvelope protobuf message.

        Returns a normalized dict like:
        {
          'from': '!12345678',     # or int id depending on firmware
          'to':   0xFFFFFFFF,      # broadcast or a node id
          'decoded': {
              'portnum': 1,        # TEXT_MESSAGE_APP
              'text': 'hello',     # if available as text
              'payload': 'hello'   # utf-8 decoded from bytes if text missing
          },
          'length': <len>
        }
        """
        if not HAVE_PROTO:
            return None

        try:
            env = mqtt_pb2.ServiceEnvelope()
            env.ParseFromString(payload)
        except Exception as e:
            # Not a protobuf service envelope
            logger.debug(f"ServiceEnvelope parse failed: {e}")
            return None

        # Pull out the MeshPacket
        pkt = env.packet

        # Field 'from' is a Python keyword; generated code exposes it as attribute "from"
        # Use getattr to be safe across versions; try 'from' and 'fromId'
        from_id = None
        for fname in ("from", "fromId", "from_", "fromId_"):
            if hasattr(pkt, fname):
                from_id = getattr(pkt, fname)
                break

        to_id = getattr(pkt, "to", None)

        # Decoded data
        decoded = getattr(pkt, "decoded", None)
        portnum = None
        text_str: Optional[str] = None
        payload_str: str = ""

        if decoded is not None:
            # Port number enum
            try:
                portnum = int(getattr(decoded, "portnum"))
            except Exception:
                portnum = None

            # Some firmware exposes 'text'; others only 'payload' as bytes
            if hasattr(decoded, "text"):
                try:
                    text_val = getattr(decoded, "text")
                    if isinstance(text_val, bytes):
                        text_str = text_val.decode("utf-8", errors="ignore")
                    else:
                        text_str = str(text_val)
                except Exception:
                    text_str = None

            # Always try payload bytes as fallback
            try:
                payload_bytes = getattr(decoded, "payload", b"")
                if isinstance(payload_bytes, bytes):
                    payload_str = payload_bytes.decode("utf-8", errors="ignore")
                else:
                    # Some versions might already be str
                    payload_str = str(payload_bytes)
            except Exception:
                payload_str = ""

        result = {
            "from": from_id if from_id is not None else "unknown",
            "to": to_id if to_id is not None else "unknown",
            "decoded": {
                "portnum": portnum if portnum is not None else 0,
                "text": text_str or "",
                "payload": payload_str,
            },
            "length": len(payload),
        }
        return result

    def is_text_message(self, packet: Dict[str, Any]) -> bool:
        """True if packet is a text message (TEXT_MESSAGE_APP)."""
        try:
            portnum = int(packet.get("decoded", {}).get("portnum", 0))
            return portnum == self.TEXT_MESSAGE_PORT
        except Exception:
            return False

    def extract_text(self, packet: Dict[str, Any]) -> Optional[str]:
        """Extract a UTF-8 string from text or payload."""
        try:
            decoded = packet.get("decoded", {})
            text = decoded.get("text", "")
            if text:
                return text
            payload = decoded.get("payload", "")
            if payload:
                return payload
            return None
        except Exception as e:
            logger.debug(f"Text extraction failed: {e}")
            return None

    def is_public_message(self, packet: Dict[str, Any]) -> bool:
        """Public if 'to' equals 0xFFFFFFFF (broadcast)."""
        try:
            to_field = packet.get("to", "")
            return to_field == 0xFFFFFFFF or str(to_field).lower() in ("0xffffffff", "ffffffff")
        except Exception:
            return False

    def get_sender_id(self, packet: Dict[str, Any]) -> str:
        """Return sender id as string (e.g., '!12345678' or numeric as str)."""
        try:
            return str(packet.get("from", "unknown"))
        except Exception:
            return "unknown"

    def get_recipient_id(self, packet: Dict[str, Any]) -> str:
        """Return recipient id as string."""
        try:
            return str(packet.get("to", "unknown"))
        except Exception:
            return "unknown"
