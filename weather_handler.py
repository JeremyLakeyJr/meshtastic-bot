"""
Weather Handler for Meshtastic AI DM Bot.
Resolves human/place input to coordinates and fetches forecast via Open-Meteo.
"""

import logging
import unicodedata
from datetime import datetime, timedelta
from typing import Optional, Tuple, List, Dict
import requests

logger = logging.getLogger(__name__)


def _ascii_clean(s: str) -> str:
    """Normalize Unicode and drop non-ASCII so Meshtastic apps don't render garbage."""
    try:
        return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().strip()
    except Exception:
        return s


def label_from_address(city: str, admin: str, country: str, fallback: str = "", max_len: int = 60) -> str:
    """
    Compose a readable label like 'Plovdiv, BG' or 'Sofia, BG' with sensible fallbacks.
    Force ASCII to avoid mojibake in some Meshtastic UIs.
    """
    parts: List[str] = []
    first = (city or "").strip() or (admin or "").strip()
    if first:
        parts.append(_ascii_clean(first))
    if country:
        cc = country.upper()
        parts.append(cc if len(cc) <= 3 else _ascii_clean(country))
    label = ", ".join(parts) or (fallback.strip() or "unknown location")
    label = label.strip(" ,")
    if len(label) > max_len:
        label = label[: max_len - 1] + "…"
    return label


class WeatherHandler:
    NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
    NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"
    METEO_URL = "https://api.open-meteo.com/v1/forecast"

    # --- location resolution ---

    def resolve_location(self, query: str) -> Optional[Tuple[float, float, str]]:
        """Resolve 'lat,lon' or free text into (lat, lon, label)."""
        if not query:
            return None
        q = query.strip()

        # Try explicit lat,lon first
        if "," in q:
            parts = [p.strip() for p in q.split(",")]
            if len(parts) == 2:
                try:
                    lat, lon = float(parts[0]), float(parts[1])
                    # Use reverse geocoder to label neatly
                    label = self.reverse_label(lat, lon) or f"{lat:.4f},{lon:.4f}"
                    return lat, lon, label
                except Exception:
                    pass

        # Fallback to Nominatim geocoding
        try:
            resp = requests.get(
                self.NOMINATIM_SEARCH,
                params={"q": q, "format": "json", "limit": 1, "addressdetails": 1},
                headers={"User-Agent": "MeshtasticBot/1.0", "Accept-Language": "en"},
                timeout=12,
            )
            resp.raise_for_status()
            results = resp.json()
            if results:
                r0 = results[0]
                lat = float(r0["lat"])
                lon = float(r0["lon"])
                addr: Dict = r0.get("address", {}) or {}

                city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or ""
                admin = addr.get("state") or addr.get("county") or addr.get("region") or ""
                country = (addr.get("country_code") or "").upper() or addr.get("country", "")

                if not (city or admin):
                    disp = (r0.get("display_name") or "").split(",")[0].strip()
                    if disp:
                        city = disp

                label = label_from_address(city, admin, country, fallback=q)
                return lat, lon, label
        except Exception as e:
            logger.warning(f"Nominatim failed for '{q}': {e}")

        return None

    def reverse_label(self, lat: float, lon: float) -> Optional[str]:
        """Reverse-geocode a clean ASCII label for given coordinates."""
        try:
            r = requests.get(
                self.NOMINATIM_REVERSE,
                params={"lat": lat, "lon": lon, "format": "json", "zoom": 10, "addressdetails": 1},
                headers={"User-Agent": "MeshtasticBot/1.0", "Accept-Language": "en"},
                timeout=12,
            )
            r.raise_for_status()
            data = r.json()
            addr = data.get("address", {}) or {}
            city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or ""
            admin = addr.get("state") or addr.get("county") or addr.get("region") or ""
            country = (addr.get("country_code") or "").upper() or addr.get("country", "")
            return label_from_address(city, admin, country, fallback=f"{lat:.4f},{lon:.4f}")
        except Exception as e:
            logger.warning(f"Nominatim reverse failed: {e}")
            return None

    # --- weather ---

    def fetch_forecast_lines(self, lat: float, lon: float) -> Tuple[List[str], List[str]]:
        """
        Fetch hourly (next 6 hours) and daily (next 3 days) forecast lines.
        Returns (hourly_lines, daily_lines).
        """
        try:
            params = {
                "latitude": lat,
                "longitude": lon,
                "hourly": "temperature_2m,precipitation_probability",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "forecast_days": 4,  # today + next 3
                "timezone": "auto",
            }
            r = requests.get(self.METEO_URL, params=params, timeout=12)
            r.raise_for_status()
            data = r.json()

            # Hourly → start from next full hour (local tz), show next 6 hours
            now = datetime.now()
            times = [datetime.fromisoformat(t) for t in data["hourly"]["time"]]
            temps = data["hourly"]["temperature_2m"]
            precs = data["hourly"]["precipitation_probability"]

            hourly: List[str] = []
            end_by = now + timedelta(hours=6, minutes=1)
            for t, temp, prec in zip(times, temps, precs):
                if t <= now:
                    continue
                if t > end_by:
                    break
                hourly.append(f"{t.strftime('%H:00')} {int(round(temp))}C, {prec}%")
            if not hourly:
                hourly = ["(no hourly data)"]

            # Daily — next 3 days (skip today index 0)
            daily: List[str] = []
            for t, tmax, tmin, pmax in zip(
                data["daily"]["time"][1:4],
                data["daily"]["temperature_2m_max"][1:4],
                data["daily"]["temperature_2m_min"][1:4],
                data["daily"]["precipitation_probability_max"][1:4],
            ):
                dt = datetime.fromisoformat(t)
                daily.append(f"{dt.strftime('%a %d %b')}: {int(round(tmin))}-{int(round(tmax))}C, {pmax}%")
            if not daily:
                daily = ["(no daily data)"]

            return hourly, daily

        except Exception as e:
            logger.error(f"Open-Meteo error: {e}")
            return ["(failed to fetch hourly)"], ["(failed to fetch daily)"]
