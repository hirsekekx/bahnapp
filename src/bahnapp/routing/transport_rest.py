"""Wrapper around v6.db.transport.rest for journey search."""
from __future__ import annotations

import logging
import time as _time
from datetime import date, datetime, time
from typing import Iterable

import httpx

from bahnapp.config import get_settings

log = logging.getLogger(__name__)


class UpstreamUnavailable(RuntimeError):
    """Raised when transport.rest is unreachable / returns persistent 5xx."""


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(base_url=s.transport_rest_base_url, timeout=30.0)


def _get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict,
    attempts: int = 3,
    backoff: float = 0.8,
) -> httpx.Response:
    """GET with retry on transient upstream errors (5xx, 429, network).

    Raises UpstreamUnavailable when all attempts fail.
    """
    last_status: int | None = None
    last_exc: Exception | None = None
    for i in range(attempts):
        try:
            resp = client.get(url, params=params)
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
            last_status = resp.status_code
            log.warning("transport.rest %s -> %s (attempt %d/%d)",
                        url, resp.status_code, i + 1, attempts)
        except httpx.RequestError as exc:
            last_exc = exc
            log.warning("transport.rest %s network error: %s (attempt %d/%d)",
                        url, exc, i + 1, attempts)
        if i < attempts - 1:
            _time.sleep(backoff * (2 ** i))
    if last_exc is not None:
        raise UpstreamUnavailable(f"transport.rest nicht erreichbar: {last_exc}") from last_exc
    raise UpstreamUnavailable(
        f"transport.rest antwortet mit {last_status} (nach {attempts} Versuchen)"
    )


def fetch_journeys_for_day(
    origin_eva: int,
    dest_eva: int,
    travel_day: date,
    max_transfers: int = 2,
    results_per_call: int = 10,
) -> list[dict]:
    """Fetch all journeys (paginated) for a given travel day.

    Starts at 04:00 local of the day and walks forward via `laterRef` until either
    the next departure is on the next calendar day or no more results are returned.
    Returns the raw `journey` dicts as delivered by transport.rest.
    """
    start_iso = datetime.combine(travel_day, time(4, 0)).isoformat()
    common = {
        "from": str(origin_eva),
        "to": str(dest_eva),
        "results": str(results_per_call),
        "stopovers": "false",
        "transfers": str(max_transfers),
        "remarks": "false",
        "polylines": "false",
        "tickets": "false",
        "subStops": "false",
        "entrances": "false",
        "national": "true",
        "nationalExpress": "true",
        "regional": "true",
        "regionalExpress": "true",
        "suburban": "false",
        "bus": "false",
        "ferry": "false",
        "tram": "false",
        "taxi": "false",
    }

    journeys: list[dict] = []
    seen_refresh_tokens: set[str] = set()

    with _client() as c:
        params = {**common, "departure": start_iso}
        resp = _get_with_retry(c, "/journeys", params=params)
        resp.raise_for_status()
        payload = resp.json()
        later_ref = payload.get("laterRef")
        for j in payload.get("journeys", []):
            tok = j.get("refreshToken")
            if tok and tok in seen_refresh_tokens:
                continue
            if tok:
                seen_refresh_tokens.add(tok)
            journeys.append(j)

        # Walk forward
        for _ in range(20):  # safety bound
            if not later_ref:
                break
            params = {**common, "laterThan": later_ref}
            resp = _get_with_retry(c, "/journeys", params=params)
            resp.raise_for_status()
            payload = resp.json()
            later_ref = payload.get("laterRef")
            new_count = 0
            for j in payload.get("journeys", []):
                tok = j.get("refreshToken")
                if tok and tok in seen_refresh_tokens:
                    continue
                first_leg_dep = j["legs"][0].get("plannedDeparture") or j["legs"][0].get("departure")
                if first_leg_dep:
                    dep_dt = datetime.fromisoformat(first_leg_dep.replace("Z", "+00:00"))
                    if dep_dt.date() > travel_day:
                        return journeys
                if tok:
                    seen_refresh_tokens.add(tok)
                journeys.append(j)
                new_count += 1
            if new_count == 0:
                break

    return journeys


def search_locations(query: str, results: int = 8) -> list[dict]:
    """Wrap /locations endpoint for stop search (used by UI autocomplete)."""
    with _client() as c:
        resp = _get_with_retry(c, "/locations", params={
            "query": query,
            "results": results,
            "stops": "true",
            "addresses": "false",
            "poi": "false",
        })
        resp.raise_for_status()
        # Filter only stops (exclude addresses/POIs) — we already pass stops=true,
        # but the API occasionally returns mixed types; keep everything with an id.
        return [loc for loc in resp.json() if loc.get("id") and loc.get("name")]
