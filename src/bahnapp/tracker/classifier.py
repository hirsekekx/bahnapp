"""Etappen-Status-Klassifikation aus StopEvents an Origin und Dest."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from bahnapp.db_api.timetables import StopEvent

DELAYED_THRESHOLD_MIN = 6
OUTAGE_DELAY_THRESHOLD_MIN = 60


@dataclass
class EtappeStatusUpdate:
    origin_status: str   # 'scheduled' | 'on_time' | 'delayed' | 'stop_cancelled' | 'cancelled'
    dest_status: str
    origin_actual: Optional[datetime]
    dest_actual: Optional[datetime]
    delay_minutes: Optional[int]
    raw_messages: dict


def _delay_min(planned: Optional[datetime], actual: Optional[datetime]) -> Optional[int]:
    if planned is None or actual is None:
        return None
    return int(round((actual - planned).total_seconds() / 60))


def _classify_endpoint(
    planned: Optional[datetime],
    actual: Optional[datetime],
    cancelled: bool,
) -> str:
    if cancelled:
        return "stop_cancelled"
    if actual is None:
        return "scheduled"
    delay = _delay_min(planned, actual) or 0
    if delay >= DELAYED_THRESHOLD_MIN:
        return "delayed"
    return "on_time"


def classify_etappe(
    origin: Optional[StopEvent],
    dest: Optional[StopEvent],
) -> EtappeStatusUpdate:
    origin_cancelled = bool(origin and origin.is_fully_cancelled)
    dest_cancelled = bool(dest and dest.is_fully_cancelled)

    origin_status = _classify_endpoint(
        origin.departure_planned if origin else None,
        origin.departure_actual if origin else None,
        origin_cancelled,
    )
    dest_status = _classify_endpoint(
        dest.arrival_planned if dest else None,
        dest.arrival_actual if dest else None,
        dest_cancelled,
    )

    if origin_cancelled and dest_cancelled:
        origin_status = "cancelled"
        dest_status = "cancelled"

    delay = _delay_min(
        dest.arrival_planned if dest else None,
        dest.arrival_actual if dest else None,
    )

    raw_messages = {}
    if origin and origin.messages:
        raw_messages["origin_msgs"] = origin.messages
    if dest and dest.messages:
        raw_messages["dest_msgs"] = dest.messages

    return EtappeStatusUpdate(
        origin_status=origin_status,
        dest_status=dest_status,
        origin_actual=origin.departure_actual if origin else None,
        dest_actual=dest.arrival_actual if dest else None,
        delay_minutes=delay,
        raw_messages=raw_messages,
    )
