"""Aggregate per-Etappe statuses into Reise-level outage state."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from bahnapp.tracker.classifier import OUTAGE_DELAY_THRESHOLD_MIN


@dataclass
class EtappeView:
    etappe_index: int
    origin_status: str
    dest_status: str
    origin_planned: datetime
    origin_actual: Optional[datetime]
    dest_planned: datetime
    dest_actual: Optional[datetime]
    delay_minutes: Optional[int]
    min_umsteige_min: Optional[int]


@dataclass
class ReiseAggregate:
    outage_state: str         # 'pending' | 'on_time' | 'delayed' | 'outage'
    outage_reason: Optional[str]   # 'etappe_cancelled' | 'stop_cancelled' | 'arr_delay_60' | 'anschluss_verpasst'
    total_delay_min: Optional[int]
    final: bool


def _connection_held(prev: EtappeView, nxt: EtappeView) -> Optional[bool]:
    """True if the transfer can be made, False if missed, None if not yet decidable."""
    if prev.min_umsteige_min is None:
        return True  # last leg has no transfer
    prev_arr = prev.dest_actual or prev.dest_planned
    nxt_dep = nxt.origin_actual or nxt.origin_planned
    if prev.dest_actual is None and nxt.origin_actual is None:
        return None
    required = prev_arr.replace(microsecond=0)
    available = nxt_dep
    delta_min = (available - required).total_seconds() / 60
    return delta_min >= prev.min_umsteige_min


def aggregate_reise(etappen: Sequence[EtappeView]) -> ReiseAggregate:
    if not etappen:
        return ReiseAggregate("pending", None, None, False)

    sorted_etappen = sorted(etappen, key=lambda e: e.etappe_index)

    # 1. Any fully cancelled etappe → outage
    for e in sorted_etappen:
        if e.origin_status == "cancelled" and e.dest_status == "cancelled":
            return ReiseAggregate("outage", "etappe_cancelled", None, True)

    # 2. Stop cancellation at a used endpoint
    for e in sorted_etappen:
        if e.origin_status == "stop_cancelled" or e.dest_status == "stop_cancelled":
            return ReiseAggregate("outage", "stop_cancelled", None, True)

    # 3. Missed transfer
    for prev, nxt in zip(sorted_etappen, sorted_etappen[1:]):
        held = _connection_held(prev, nxt)
        if held is False:
            return ReiseAggregate("outage", "anschluss_verpasst", None, True)

    last = sorted_etappen[-1]

    # 4. Arrival delay >= 60 at the final destination
    if last.delay_minutes is not None and last.delay_minutes >= OUTAGE_DELAY_THRESHOLD_MIN:
        return ReiseAggregate("outage", "arr_delay_60", last.delay_minutes, True)

    # 5. Has the journey concluded? Need the final-leg dest_actual to call it final.
    final = last.dest_actual is not None
    if not final:
        # If still pending real-time confirmation but every etappe shows on_time/delayed,
        # report a tentative state.
        if any(e.dest_status == "scheduled" or e.origin_status == "scheduled"
               for e in sorted_etappen):
            return ReiseAggregate("pending", None, None, False)

    # 6. on_time vs. delayed
    if last.delay_minutes is not None and last.delay_minutes >= 6:
        return ReiseAggregate("delayed", None, last.delay_minutes, final)
    if any(e.origin_status == "delayed" or e.dest_status == "delayed"
           for e in sorted_etappen):
        return ReiseAggregate("delayed", None, last.delay_minutes, final)
    return ReiseAggregate("on_time", None, last.delay_minutes, final)
