"""Poll worker: process due poll_tasks → update etappen → aggregate reisen."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from bahnapp.db.models import PollTask, PollTaskEtappe, Reise, ReiseEtappe
from bahnapp.db.session import session_scope
from bahnapp.db_api.timetables import StopEvent, fetch_station_state
from bahnapp.tracker.aggregator import EtappeView, aggregate_reise
from bahnapp.tracker.classifier import classify_etappe

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
STALE_TASK_AGE_HOURS = 2
BATCH_SIZE = 50


def _hours_to_load(target: datetime) -> list[datetime]:
    """Return candidate hours to query: the target hour and the previous one."""
    base = target.replace(minute=0, second=0, microsecond=0)
    return [base - timedelta(hours=1), base, base + timedelta(hours=1)]


def _match_stop_event(events: dict[str, StopEvent], train_number: str,
                      planned: datetime, role: str) -> Optional[StopEvent]:
    """Match the StopEvent for given train_number and role ('arrival' or 'departure').

    Falls back to fuzzy time matching (±90 min) if no exact planned-time hit.
    """
    candidates = [e for e in events.values() if e.train_number == train_number]
    if not candidates:
        return None
    best: Optional[StopEvent] = None
    best_diff = timedelta(days=1)
    for ev in candidates:
        ref = ev.arrival_planned if role == "arrival" else ev.departure_planned
        if ref is None:
            continue
        diff = abs(ref - planned)
        if diff < best_diff:
            best_diff = diff
            best = ev
    if best is not None and best_diff <= timedelta(minutes=90):
        return best
    return None


def _process_etappe(session: Session, etappe: ReiseEtappe,
                    poll_role: str) -> None:
    """Update etappe with current real-time state. poll_role: 'origin' or 'dest'."""
    if poll_role == "origin":
        target = etappe.origin_planned
        eva = etappe.origin_eva
        role = "departure"
    else:
        target = etappe.dest_planned
        eva = etappe.dest_eva
        role = "arrival"

    events = fetch_station_state(eva, _hours_to_load(target))
    matched = _match_stop_event(events, etappe.train_number, target, role)

    # Always re-fetch the counterpart endpoint too (cheap if cached) so the
    # classifier sees both sides on the final task.
    other_eva = etappe.dest_eva if poll_role == "origin" else etappe.origin_eva
    other_target = etappe.dest_planned if poll_role == "origin" else etappe.origin_planned
    other_role = "arrival" if poll_role == "origin" else "departure"
    if other_eva == eva:
        other_events = events
    else:
        other_events = fetch_station_state(other_eva, _hours_to_load(other_target))
    other_matched = _match_stop_event(other_events, etappe.train_number, other_target, other_role)

    origin_ev = matched if poll_role == "origin" else other_matched
    dest_ev = matched if poll_role == "dest" else other_matched

    update = classify_etappe(origin_ev, dest_ev)
    if update.origin_actual is not None:
        etappe.origin_actual = update.origin_actual
    if update.dest_actual is not None:
        etappe.dest_actual = update.dest_actual
    if update.delay_minutes is not None:
        etappe.delay_minutes = update.delay_minutes
    etappe.origin_status = update.origin_status
    etappe.dest_status = update.dest_status
    if update.raw_messages:
        etappe.raw_messages = update.raw_messages
    etappe.last_updated = datetime.now()


def _aggregate_reise(session: Session, reise: Reise) -> None:
    etappen = session.execute(
        select(ReiseEtappe)
        .where(ReiseEtappe.reise_id == reise.id)
        .order_by(ReiseEtappe.etappe_index)
    ).scalars().all()
    views = [
        EtappeView(
            etappe_index=e.etappe_index,
            origin_status=e.origin_status,
            dest_status=e.dest_status,
            origin_planned=e.origin_planned,
            origin_actual=e.origin_actual,
            dest_planned=e.dest_planned,
            dest_actual=e.dest_actual,
            delay_minutes=e.delay_minutes,
            min_umsteige_min=e.min_umsteige_min,
        ) for e in etappen
    ]
    agg = aggregate_reise(views)
    reise.outage_state = agg.outage_state
    reise.outage_reason = agg.outage_reason
    reise.total_delay_min = agg.total_delay_min
    reise.last_updated = datetime.now()
    if agg.final and reise.finalized_at is None:
        reise.finalized_at = datetime.now()
        if agg.outage_state == "outage" and agg.outage_reason in (
            "etappe_cancelled", "stop_cancelled"
        ):
            _short_circuit_remaining_polls(session, reise.id)


def _short_circuit_remaining_polls(session: Session, reise_id: int) -> None:
    """Mark all remaining pending poll_tasks of this reise as done."""
    etappen_ids = session.execute(
        select(ReiseEtappe.id).where(ReiseEtappe.reise_id == reise_id)
    ).scalars().all()
    if not etappen_ids:
        return
    task_ids = session.execute(
        select(PollTaskEtappe.poll_task_id).where(PollTaskEtappe.etappe_id.in_(etappen_ids))
    ).scalars().all()
    if not task_ids:
        return
    session.execute(
        PollTask.__table__.update()
        .where(PollTask.id.in_(task_ids), PollTask.status == "pending")
        .values(status="done")
    )


def run_once() -> int:
    """Process one batch of due tasks. Returns count processed."""
    now = datetime.now()
    processed = 0
    with session_scope() as sess:
        # Drop very stale pending tasks
        sess.execute(
            PollTask.__table__.update()
            .where(
                PollTask.status == "pending",
                PollTask.scheduled_at < now - timedelta(hours=STALE_TASK_AGE_HOURS),
            )
            .values(status="failed")
        )

        tasks = sess.execute(
            select(PollTask)
            .where(PollTask.status == "pending", PollTask.scheduled_at <= now)
            .order_by(PollTask.scheduled_at)
            .limit(BATCH_SIZE)
        ).scalars().all()

        affected_reisen: set[int] = set()

        for task in tasks:
            poll_role = "origin" if task.reason in ("pre_dep_60", "pre_dep_5", "post_dep_5") else "dest"
            try:
                links = sess.execute(
                    select(PollTaskEtappe.etappe_id).where(
                        PollTaskEtappe.poll_task_id == task.id
                    )
                ).scalars().all()
                if not links:
                    task.status = "done"
                    task.attempted_at = now
                    continue
                etappen = sess.execute(
                    select(ReiseEtappe).where(ReiseEtappe.id.in_(links))
                ).scalars().all()
                for et in etappen:
                    _process_etappe(sess, et, poll_role)
                    affected_reisen.add(et.reise_id)
                task.status = "done"
                task.attempted_at = now
                task.attempts = (task.attempts or 0) + 1
                processed += 1
            except Exception as exc:
                log.warning("poll task %s failed: %s", task.id, exc)
                task.attempts = (task.attempts or 0) + 1
                task.attempted_at = now
                if task.attempts >= MAX_ATTEMPTS:
                    task.status = "failed"

        for reise_id in affected_reisen:
            reise = sess.get(Reise, reise_id)
            if reise is not None:
                _aggregate_reise(sess, reise)

    return processed
