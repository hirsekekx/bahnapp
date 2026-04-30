"""Translate Etappen → poll_tasks. Idempotent (UNIQUE constraint based dedupe)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from bahnapp.db.models import PollTask, PollTaskEtappe, ReiseEtappe

log = logging.getLogger(__name__)


# (offset_minutes, eva_field, reason)
# eva_field: 'origin' or 'dest'
POLL_PLAN: list[tuple[int, str, str]] = [
    (-60, "origin", "pre_dep_60"),
    (-5,  "origin", "pre_dep_5"),
    (+5,  "origin", "post_dep_5"),
    (-5,  "dest",   "pre_arr_5"),
    (+5,  "dest",   "post_arr_5"),
    (+30, "dest",   "post_arr_30"),
]

BUCKET_MINUTES = 15


def floor_to_bucket(dt: datetime, minutes: int = BUCKET_MINUTES) -> datetime:
    discard = (dt.minute % minutes)
    return dt.replace(minute=dt.minute - discard, second=0, microsecond=0)


def compute_tasks_for_etappe(etappe: ReiseEtappe) -> list[tuple[int, datetime, str]]:
    """Return list of (eva_no, scheduled_at_bucketed, reason) for one Etappe."""
    out = []
    for offset, eva_field, reason in POLL_PLAN:
        if eva_field == "origin":
            base = etappe.origin_planned
            eva = etappe.origin_eva
        else:
            base = etappe.dest_planned
            eva = etappe.dest_eva
        scheduled_at = floor_to_bucket(base + timedelta(minutes=offset))
        out.append((eva, scheduled_at, reason))
    return out


def schedule_etappe(session: Session, etappe: ReiseEtappe) -> int:
    """Create poll_tasks for the given etappe (idempotent). Returns count of new links."""
    triples = compute_tasks_for_etappe(etappe)
    new_links = 0
    for eva, scheduled_at, reason in triples:
        # UPSERT to get an existing or newly inserted poll_task id
        stmt = (
            mysql_insert(PollTask)
            .values(eva_no=eva, scheduled_at=scheduled_at, reason=reason, status="pending")
            .on_duplicate_key_update(eva_no=eva)  # no-op update to allow returning existing row
        )
        session.execute(stmt)

        existing = session.execute(
            select(PollTask).where(
                PollTask.eva_no == eva,
                PollTask.scheduled_at == scheduled_at,
                PollTask.reason == reason,
            )
        ).scalar_one()

        link_exists = session.execute(
            select(PollTaskEtappe).where(
                PollTaskEtappe.poll_task_id == existing.id,
                PollTaskEtappe.etappe_id == etappe.id,
            )
        ).first()
        if not link_exists:
            session.add(PollTaskEtappe(poll_task_id=existing.id, etappe_id=etappe.id))
            new_links += 1
    return new_links


def schedule_etappen(session: Session, etappen: Iterable[ReiseEtappe]) -> int:
    total = 0
    for e in etappen:
        total += schedule_etappe(session, e)
    return total
