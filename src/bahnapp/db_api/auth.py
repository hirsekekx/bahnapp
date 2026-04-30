from __future__ import annotations

from bahnapp.config import get_settings


def auth_headers() -> dict[str, str]:
    """DB Timetables API uses simple header-based auth (client_id + api_key)."""
    s = get_settings()
    return {
        "DB-Client-Id": s.db_api_client_id,
        "DB-Api-Key": s.db_api_client_secret,
        "Accept": "application/xml",
    }
