"""
AI Handler for Meshtastic AI DM Bot.
Manages Google Gemini API interactions and response generation with per-user chat context.
"""

import logging
import time
from typing import Optional, Dict, List

import google.generativeai as genai

logger = logging.getLogger(__name__)


class AIHandler:
    """Handles AI interactions using Google Gemini with per-user chat sessions."""
    
    def __init__(self, api_key: str, model_name: str = "gemini-1.5-flash"):
        """
        Initialize AI handler.

        Args:
            api_key: Google Gemini API key
            model_name: Gemini model to use
        """
        self.api_key = api_key
        self.model_name = model_name
        self.model = None

        # Retry policy
        self.max_retries = 3
        self.retry_delay = 1.0

        # Length targets (characters)
        self.min_chars = 200
        self.max_chars = 600
        self.ideal_low = 250
        self.ideal_high = 450

        # Generation config tuned for compact, informative replies.
        # Note: tokens ≠ characters, but 160–220 tokens typically stays well under 600 chars.
        self.generation_config = {
            "temperature": 0.6,
            "top_p": 0.8,
            "top_k": 40,
            "max_output_tokens": 200,
        }

        # In-memory chat sessions keyed by user_id (string)
        self._chats: Dict[str, any] = {}

        # One-time brevity preamble injected when a new chat is created.
        self._brevity_preamble = (
            "You are a Meshtastic DM bot with strict brevity rules.\n"
            "- Aim for ~250–450 characters total.\n"
            "- Never under 200 chars; never over 600 chars.\n"
            "- 1–3 short bullet points OR one concise paragraph.\n"
            "- No greetings/preamble/fluff; deliver facts/steps.\n"
            "- If listing steps, use '- <step>'."
        )

        self._setup_model()

    def _setup_model(self):
        """Initialize the Gemini model."""
        try:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config=self.generation_config,
            )
            logger.info(f"Gemini model '{self.model_name}' initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model: {e}")
            raise

    def _get_or_create_chat(self, user_id: str):
        """Return an existing chat session or create a new one for user_id."""
        chat = self._chats.get(user_id)
        if chat is None:
            chat = self.model.start_chat(
                history=[
                    {"role": "user", "parts": [self._brevity_preamble]},
                    {"role": "model", "parts": ["OK"]},
                ]
            )
            self._chats[user_id] = chat
        return chat

    @staticmethod
    def _extract_text(response) -> str:
        """Extract text robustly from a Gemini response object."""
        # Preferred: response.text
        try:
            if hasattr(response, "text") and response.text:
                return response.text
        except Exception:
            pass

        # Fallback: dig through candidates/parts if available
        try:
            cand0 = getattr(response, "candidates", [None])[0]
            if cand0 and hasattr(cand0, "content"):
                parts = getattr(cand0.content, "parts", []) or []
                texts: List[str] = []
                for p in parts:
                    t = getattr(p, "text", None)
                    if not t and isinstance(p, dict):
                        t = p.get("text")
                    if t:
                        texts.append(t)
                if texts:
                    return "\n".join(texts)
        except Exception:
            pass

        # Last resort: string cast
        return str(response)

    def _clean_whitespace(self, s: str) -> str:
        return " ".join(s.split())

    def _trim_to_max_chars(self, s: str) -> str:
        """Trim at sentence boundaries to <= max_chars when possible."""
        s = s.strip()
        if len(s) <= self.max_chars:
            return s

        # Try to trim on sentence end near the max boundary
        cutoff = self.max_chars
        candidates = []
        for p in [". ", "! ", "? ", "\n", " - "]:
            idx = s.rfind(p, 0, cutoff)
            if idx != -1:
                candidates.append(idx + len(p.strip()))
        if candidates:
            return s[:max(candidates)].strip()

        # Fallback: hard cut
        return s[:self.max_chars].rstrip()

    def _ensure_length_bounds(self, chat, base_prompt: str, first_try_text: str) -> str:
        """
        If too short, request one-time expansion. If too long, trim neatly.
        """
        text = self._clean_whitespace(first_try_text)

        if len(text) < self.min_chars:
            # One expansion attempt to reach ~ideal range
            try:
                expand_prompt = (
                    "Please expand the previous answer to roughly "
                    f"{self.ideal_low}–{self.ideal_high} characters. "
                    "Do not add fluff; add only essential specifics."
                )
                resp = chat.send_message(expand_prompt)
                expanded = self._extract_text(resp).strip()
                expanded = self._clean_whitespace(expanded) or text
                text = expanded
            except Exception as e:
                logger.warning(f"Expansion step failed: {e}")

        if len(text) > self.max_chars:
            text = self._trim_to_max_chars(text)

        return text

    def chat_respond(self, user_id: str, prompt: str) -> str:
        """
        Send a prompt in the user's chat session and return the response text
        within 200–600 characters (1–3 Meshtastic frames).
        """
        if not self.model:
            raise Exception("AI model not initialized")

        chat = self._get_or_create_chat(user_id)

        concise_prompt = (
            f"{prompt}\n\n"
            "(Reply concisely per rules: ~250–450 chars total; never under 200 or over 600; "
            "use 1–3 short bullets or a compact paragraph; no fluff.)"
        )

        for attempt in range(self.max_retries):
            try:
                resp = chat.send_message(concise_prompt)
                raw = self._extract_text(resp).strip()
                if raw:
                    bounded = self._ensure_length_bounds(chat, concise_prompt, raw)
                    logger.info(
                        f"AI chat response (attempt {attempt + 1}) len={len(bounded)}"
                    )
                    return bounded

                logger.warning(f"Empty AI chat response (attempt {attempt + 1})")
            except Exception as e:
                logger.warning(f"AI chat attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error("All AI chat attempts failed")
                    raise Exception(f"AI generation failed after {self.max_retries} attempts: {e}")

        return "I’m having trouble responding right now. Please try again."

    # Backward-compatible one-shot interface (unused by main but kept for tooling/tests)
    def generate_response(self, prompt: str, user_context: Optional[str] = None) -> str:
        chat_id = user_context or "default"
        return self.chat_respond(chat_id, prompt)

    def test_connection(self) -> bool:
        try:
            txt = self.chat_respond("selftest", "Hello! Please reply with: ok")
            return bool(txt)
        except Exception as e:
            logger.error(f"AI connection test failed: {e}")
            return False

    def get_model_info(self) -> dict:
        return {
            "model_name": self.model_name,
            "api_key_configured": bool(self.api_key),
            "model_initialized": self.model is not None,
            "generation_config": self.generation_config,
        }

    def update_generation_config(self, new_config: dict):
        """Update generation config and recreate the model (resets chats)."""
        try:
            self.generation_config.update(new_config)
            self._setup_model()
            self._chats.clear()
            logger.info("Generation configuration updated successfully; chats reset.")
        except Exception as e:
            logger.error(f"Failed to update generation configuration: {e}")
            raise
