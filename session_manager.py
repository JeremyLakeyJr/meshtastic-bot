"""
Session Manager for Meshtastic AI DM Bot.
Handles user sessions, authentication, state, cached locations, and weather wait flags.
"""

import time
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class UserSession:
    """Represents a user session."""
    user_id: str
    created_at: float
    last_activity: float
    is_active: bool = True

    def update_activity(self):
        self.last_activity = time.time()

    def is_expired(self, max_idle_time: int = 3600) -> bool:
        return time.time() - self.last_activity > max_idle_time


class SessionManager:
    """Manages user sessions for the bot, plus per-user weather state."""

    def __init__(self, session_timeout: int = 3600):
        self.sessions: Dict[str, UserSession] = {}
        self.session_timeout = session_timeout
        self.cleanup_interval = 300  # every 5 minutes
        self.last_cleanup = time.time()

        # Weather-specific state
        self._waiting_weather_deadline: Dict[str, float] = {}  # user_id -> deadline epoch
        self._waiting_weather_pending: Dict[str, bool] = {}    # user_id -> has pending request
        self._cached_locations: Dict[str, Tuple[float, float, str]] = {}  # user_id -> (lat, lon, label)
        
        # Email-specific state
        self._waiting_email_recipient: Dict[str, bool] = {}    # user_id -> waiting for recipient email
        self._waiting_email_subject: Dict[str, bool] = {}      # user_id -> waiting for email subject
        self._waiting_email_body: Dict[str, bool] = {}         # user_id -> waiting for email body
        self._email_draft: Dict[str, Dict] = {}               # user_id -> email draft data

    # ---- basic sessions ----

    def create_session(self, user_id: str) -> UserSession:
        now = time.time()
        if user_id in self.sessions:
            s = self.sessions[user_id]
            s.update_activity()
            s.is_active = True
            logger.info(f"Refreshed session for user: {user_id}")
        else:
            s = UserSession(user_id=user_id, created_at=now, last_activity=now)
            self.sessions[user_id] = s
            logger.info(f"Created new session for user: {user_id}")
        return s

    def get_session(self, user_id: str) -> Optional[UserSession]:
        s = self.sessions.get(user_id)
        if not s:
            return None
        if s.is_expired(self.session_timeout):
            s.is_active = False
            logger.info(f"Session expired for user: {user_id}")
            return None
        if not s.is_active:
            return None
        s.update_activity()
        return s

    def has_active_session(self, user_id: str) -> bool:
        return self.get_session(user_id) is not None

    def end_session(self, user_id: str) -> bool:
        if user_id in self.sessions:
            self.sessions[user_id].is_active = False
            logger.info(f"Ended session for user: {user_id}")
            return True
        return False

    # ---- cleanup ----

    def cleanup_expired_sessions(self):
        now = time.time()
        if now - self.last_cleanup < self.cleanup_interval:
            return
        expired = [u for u, s in self.sessions.items() if s.is_expired(self.session_timeout)]
        for u in expired:
            del self.sessions[u]
        if expired:
            logger.info(f"Cleaned up {len(expired)} expired sessions")
        self.last_cleanup = now

    # ---- weather helpers ----

    def set_waiting_for_weather_location(self, user_id: str, waiting: bool, timeout_sec: int = 20):
        if waiting:
            self._waiting_weather_deadline[user_id] = time.time() + timeout_sec
            self._waiting_weather_pending[user_id] = True
        else:
            self._waiting_weather_deadline.pop(user_id, None)
            self._waiting_weather_pending.pop(user_id, None)

    def is_waiting_for_weather_location(self, user_id: str) -> bool:
        """True when we are waiting *and* still within the timeout window."""
        deadline = self._waiting_weather_deadline.get(user_id)
        if not deadline:
            return False
        if time.time() > deadline:
            # Do not auto-clear pending flag here; timer will handle user messaging.
            return False
        return True

    def has_pending_weather_request(self, user_id: str) -> bool:
        """True if a weather location request is outstanding (until explicitly cleared)."""
        return self._waiting_weather_pending.get(user_id, False)

    def clear_pending_weather_request(self, user_id: str):
        self._waiting_weather_pending.pop(user_id, None)
        self._waiting_weather_deadline.pop(user_id, None)

    def cache_location(self, user_id: str, lat: float, lon: float, label: str):
        self._cached_locations[user_id] = (lat, lon, label)

    def get_cached_location(self, user_id: str) -> Optional[Tuple[float, float, str]]:
        return self._cached_locations.get(user_id)

    def clear_cached_location(self, user_id: str):
        """Forget cached location and any pending weather wait for this user."""
        self._cached_locations.pop(user_id, None)
        self.clear_pending_weather_request(user_id)
    
    # ---- email helpers ----
    
    def set_waiting_for_email_recipient(self, user_id: str, waiting: bool):
        """Set whether user is waiting to provide email recipient."""
        if waiting:
            self._waiting_email_recipient[user_id] = True
        else:
            self._waiting_email_recipient.pop(user_id, None)
    
    def set_waiting_for_email_subject(self, user_id: str, waiting: bool):
        """Set whether user is waiting to provide email subject."""
        if waiting:
            self._waiting_email_subject[user_id] = True
        else:
            self._waiting_email_subject.pop(user_id, None)
    
    def set_waiting_for_email_body(self, user_id: str, waiting: bool):
        """Set whether user is waiting to provide email body."""
        if waiting:
            self._waiting_email_body[user_id] = True
        else:
            self._waiting_email_body.pop(user_id, None)
    
    def is_waiting_for_email_recipient(self, user_id: str) -> bool:
        """Check if user is waiting to provide email recipient."""
        return self._waiting_email_recipient.get(user_id, False)
    
    def is_waiting_for_email_subject(self, user_id: str) -> bool:
        """Check if user is waiting to provide email subject."""
        return self._waiting_email_subject.get(user_id, False)
    
    def is_waiting_for_email_body(self, user_id: str) -> bool:
        """Check if user is waiting to provide email body."""
        return self._waiting_email_body.get(user_id, False)
    
    def set_email_draft(self, user_id: str, draft_data: Dict):
        """Set email draft data for a user."""
        self._email_draft[user_id] = draft_data
    
    def get_email_draft(self, user_id: str) -> Optional[Dict]:
        """Get email draft data for a user."""
        return self._email_draft.get(user_id)
    
    def clear_email_draft(self, user_id: str):
        """Clear email draft data for a user."""
        self._email_draft.pop(user_id, None)
    
    def clear_all_email_states(self, user_id: str):
        """Clear all email-related states for a user."""
        self.set_waiting_for_email_recipient(user_id, False)
        self.set_waiting_for_email_subject(user_id, False)
        self.set_waiting_for_email_body(user_id, False)
        self.clear_email_draft(user_id)

    # ---- info helpers ----

    def get_active_session_count(self) -> int:
        self.cleanup_expired_sessions()
        return len([s for s in self.sessions.values() if s.is_active])

    def get_session_info(self, user_id: str) -> Optional[Dict]:
        s = self.get_session(user_id)
        if not s:
            return None
        return {
            "user_id": s.user_id,
            "created_at": s.created_at,
            "last_activity": s.last_activity,
            "is_active": s.is_active,
            "age_seconds": time.time() - s.created_at,
            "idle_seconds": time.time() - s.last_activity,
        }

    def list_active_sessions(self) -> Dict[str, Dict]:
        self.cleanup_expired_sessions()
        return {u: self.get_session_info(u) for u, s in self.sessions.items() if s.is_active}
