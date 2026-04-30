"""Station-Lookup. Primary source: transport.rest /locations (no auth).

Used as a thin convenience helper; the routing module also has a /locations call.
"""
from __future__ import annotations

import httpx

from bahnapp.config import get_settings


def search_stations(query: str, results: int = 8) -> list[dict]:
    s = get_settings()
    resp = httpx.get(
        f"{s.transport_rest_base_url}/locations",
        params={"query": query, "results": results, "stops": "true", "addresses": "false",
                "poi": "false"},
        timeout=10.0,
    )
    resp.raise_for_status()
    out = []
    for loc in resp.json():
        if loc.get("type") != "stop":
            continue
        out.append({
            "eva_no": int(loc["id"]),
            "name": loc.get("name", ""),
        })
    return out
