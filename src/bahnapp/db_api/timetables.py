"""DB Timetables API client (Soll-Plan + Echtzeit-Diffs).

Endpoints:
  GET /db-api-marketplace/apis/timetables/v1/plan/{evaNo}/{YYMMDD}/{HH}
  GET /db-api-marketplace/apis/timetables/v1/fchg/{evaNo}

XML format reference: https://developers.deutschebahn.com/db-api-marketplace/apis/product/timetables
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import httpx
from lxml import etree

from bahnapp.config import get_settings
from bahnapp.db_api.auth import auth_headers

log = logging.getLogger(__name__)

_BASE_PATH = "/db-api-marketplace/apis/timetables/v1"


@dataclass
class StopEvent:
    """Ein Halt eines Zuges an einer Station, kombiniert aus Plan- und Echtzeit-Daten."""

    train_number: str          # z.B. "ICE 691"
    trip_label: str            # z.B. "ICE" (Gattung)
    eva_no: int
    arrival_planned: Optional[datetime] = None
    arrival_actual: Optional[datetime] = None
    departure_planned: Optional[datetime] = None
    departure_actual: Optional[datetime] = None
    arrival_cancelled: bool = False
    departure_cancelled: bool = False
    stop_id: Optional[str] = None
    messages: list[str] = field(default_factory=list)

    @property
    def is_fully_cancelled(self) -> bool:
        return self.arrival_cancelled and self.departure_cancelled


def _parse_dt(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    return datetime.strptime(raw, "%y%m%d%H%M")


def _format_train_number(s_elem) -> tuple[str, str]:
    """Return (train_number, gattung) from an <s> element.

    XML structure: <s id="..."><tl c="ICE" n="691" .../>...</s>
    """
    tl = s_elem.find("tl")
    if tl is None:
        return ("", "")
    gattung = tl.get("c", "")
    nummer = tl.get("n", "")
    return (f"{gattung} {nummer}".strip(), gattung)


def _has_cancellation_msg(elem) -> bool:
    """Check for <m t="c"/> message marking a cancellation."""
    for m in elem.findall("m"):
        if m.get("t") == "c":
            return True
    return False


def parse_plan_xml(xml_bytes: bytes, eva_no: int) -> dict[str, StopEvent]:
    """Parse a /plan/... response. Returns map keyed by stop_id (`s/@id`).

    Each <s> element represents one stop event of one train at this station.
    Plan data has only `pt` (planned time) attributes on `<ar>` and `<dp>`.
    """
    out: dict[str, StopEvent] = {}
    if not xml_bytes:
        return out
    root = etree.fromstring(xml_bytes)
    for s in root.findall("s"):
        stop_id = s.get("id", "")
        train_number, gattung = _format_train_number(s)
        if not train_number:
            continue
        ar = s.find("ar")
        dp = s.find("dp")
        ev = StopEvent(
            train_number=train_number,
            trip_label=gattung,
            eva_no=eva_no,
            stop_id=stop_id,
            arrival_planned=_parse_dt(ar.get("pt")) if ar is not None else None,
            departure_planned=_parse_dt(dp.get("pt")) if dp is not None else None,
        )
        out[stop_id] = ev
    return out


def merge_fchg_xml(xml_bytes: bytes, plan: dict[str, StopEvent]) -> None:
    """Merge realtime diffs from /fchg/... into the plan dict (in place).

    The fchg response has the same structure but only stops with changes.
    Cancellations carry `<m t="c"/>`. Actual times in `ar/@ct`, `dp/@ct`.
    """
    if not xml_bytes:
        return
    root = etree.fromstring(xml_bytes)
    for s in root.findall("s"):
        stop_id = s.get("id", "")
        ev = plan.get(stop_id)
        if ev is None:
            train_number, gattung = _format_train_number(s)
            if not train_number:
                continue
            ev = StopEvent(
                train_number=train_number,
                trip_label=gattung,
                eva_no=ev.eva_no if ev else 0,
                stop_id=stop_id,
            )
            plan[stop_id] = ev

        ar = s.find("ar")
        if ar is not None:
            if ar.get("ct"):
                ev.arrival_actual = _parse_dt(ar.get("ct"))
            if not ev.arrival_planned and ar.get("pt"):
                ev.arrival_planned = _parse_dt(ar.get("pt"))
            if _has_cancellation_msg(ar):
                ev.arrival_cancelled = True
        dp = s.find("dp")
        if dp is not None:
            if dp.get("ct"):
                ev.departure_actual = _parse_dt(dp.get("ct"))
            if not ev.departure_planned and dp.get("pt"):
                ev.departure_planned = _parse_dt(dp.get("pt"))
            if _has_cancellation_msg(dp):
                ev.departure_cancelled = True
        if _has_cancellation_msg(s):
            ev.arrival_cancelled = True
            ev.departure_cancelled = True
        for m in s.findall(".//m"):
            mid = m.get("id")
            if mid:
                ev.messages.append(mid)


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        base_url=f"{s.db_api_base_url}{_BASE_PATH}",
        headers=auth_headers(),
        timeout=20.0,
    )


def fetch_plan(eva_no: int, dt: datetime) -> dict[str, StopEvent]:
    """Fetch /plan/{eva}/{YYMMDD}/{HH} for the given hour and return parsed events."""
    yymmdd = dt.strftime("%y%m%d")
    hh = dt.strftime("%H")
    with _client() as c:
        resp = c.get(f"/plan/{eva_no}/{yymmdd}/{hh}")
        resp.raise_for_status()
        return parse_plan_xml(resp.content, eva_no)


def fetch_fchg(eva_no: int) -> bytes:
    """Fetch /fchg/{eva} (raw XML) — caller merges via merge_fchg_xml."""
    with _client() as c:
        resp = c.get(f"/fchg/{eva_no}")
        resp.raise_for_status()
        return resp.content


def fetch_station_state(eva_no: int, hours: list[datetime]) -> dict[str, StopEvent]:
    """Convenience: load plan for several hours + merge fchg → unified stop map."""
    merged: dict[str, StopEvent] = {}
    for h in hours:
        try:
            merged.update(fetch_plan(eva_no, h))
        except httpx.HTTPError as exc:
            log.warning("plan fetch failed eva=%s hour=%s: %s", eva_no, h, exc)
    try:
        merge_fchg_xml(fetch_fchg(eva_no), merged)
    except httpx.HTTPError as exc:
        log.warning("fchg fetch failed eva=%s: %s", eva_no, exc)
    return merged
