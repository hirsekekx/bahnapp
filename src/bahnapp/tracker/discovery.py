"""Discovery: 1×/Tag pro aktivem Job → Reisen+Etappen für rollierendes Fenster."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from bahnapp.config import get_settings
from bahnapp.db.models import (
    PollTask,
    PollTaskEtappe,
    Reise,
    ReiseEtappe,
    Station,
    TrackingJob,
)
from bahnapp.db.session import session_scope
from bahnapp.routing.normalize import (
    NormalizedReise,
    allowed_gattungen,
    normalize_journey,
)
from bahnapp.routing.transport_rest import fetch_journeys_for_day
from bahnapp.tracker.scheduler import schedule_etappe

log = logging.getLogger(__name__)


def _ensure_station(session: Session, eva_no: int, name: str = "") -> None:
    exists = session.execute(select(Station).where(Station.eva_no == eva_no)).scalar_one_or_none()
    if exists is None:
        session.add(Station(eva_no=eva_no, name=name or str(eva_no), updated_at=datetime.now()))
        session.flush()


def _upsert_reise(session: Session, job: TrackingJob, travel_day: date,
                  norm: NormalizedReise) -> Reise:
    existing = session.execute(
        select(Reise).where(
            Reise.job_id == job.id,
            Reise.travel_date == travel_day,
            Reise.planned_departure == norm.planned_departure,
            Reise.anzahl_etappen == norm.anzahl_etappen,
        )
    ).scalar_one_or_none()

    now = datetime.now()
    if existing is None:
        reise = Reise(
            job_id=job.id,
            travel_date=travel_day,
            refresh_token=norm.refresh_token,
            planned_departure=norm.planned_departure,
            planned_arrival=norm.planned_arrival,
            anzahl_etappen=norm.anzahl_etappen,
            outage_state="pending",
            last_updated=now,
        )
        session.add(reise)
        session.flush()
    else:
        existing.refresh_token = norm.refresh_token
        existing.planned_arrival = norm.planned_arrival
        existing.last_updated = now
        reise = existing

    # UPSERT etappen
    existing_etappen = {
        e.etappe_index: e for e in
        session.execute(select(ReiseEtappe).where(ReiseEtappe.reise_id == reise.id)).scalars()
    }
    for nr_etappe in norm.etappen:
        _ensure_station(session, nr_etappe.origin_eva)
        _ensure_station(session, nr_etappe.dest_eva)
        e = existing_etappen.get(nr_etappe.etappe_index)
        if e is None:
            e = ReiseEtappe(
                reise_id=reise.id,
                etappe_index=nr_etappe.etappe_index,
                train_number=nr_etappe.train_number,
                hafas_trip_id=nr_etappe.hafas_trip_id,
                origin_eva=nr_etappe.origin_eva,
                dest_eva=nr_etappe.dest_eva,
                origin_planned=nr_etappe.origin_planned,
                dest_planned=nr_etappe.dest_planned,
                min_umsteige_min=nr_etappe.min_umsteige_min,
                last_updated=now,
            )
            session.add(e)
            session.flush()
        else:
            changed = (
                e.train_number != nr_etappe.train_number
                or e.origin_planned != nr_etappe.origin_planned
                or e.dest_planned != nr_etappe.dest_planned
                or e.origin_eva != nr_etappe.origin_eva
                or e.dest_eva != nr_etappe.dest_eva
            )
            if changed:
                _purge_pending_tasks_for_etappe(session, e.id)
                e.train_number = nr_etappe.train_number
                e.hafas_trip_id = nr_etappe.hafas_trip_id
                e.origin_eva = nr_etappe.origin_eva
                e.dest_eva = nr_etappe.dest_eva
                e.origin_planned = nr_etappe.origin_planned
                e.dest_planned = nr_etappe.dest_planned
            e.min_umsteige_min = nr_etappe.min_umsteige_min
            e.last_updated = now

        schedule_etappe(session, e)

    return reise


def _purge_pending_tasks_for_etappe(session: Session, etappe_id: int) -> None:
    """Drop pending poll_task links for a changed etappe so new ones can be scheduled."""
    rows = session.execute(
        select(PollTaskEtappe.poll_task_id).where(PollTaskEtappe.etappe_id == etappe_id)
    ).scalars().all()
    if not rows:
        return
    session.execute(
        PollTaskEtappe.__table__.delete().where(PollTaskEtappe.etappe_id == etappe_id)
    )
    # Tasks that are still pending and now orphaned can be marked done so the worker skips them.
    for tid in rows:
        still_linked = session.execute(
            select(PollTaskEtappe).where(PollTaskEtappe.poll_task_id == tid)
        ).first()
        if still_linked is None:
            session.execute(
                PollTask.__table__.update()
                .where(PollTask.id == tid, PollTask.status == "pending")
                .values(status="done")
            )


def discover_for_job_day(session: Session, job: TrackingJob, day: date) -> int:
    """Run discovery for one job + one day. Returns number of reisen upserted."""
    raw = fetch_journeys_for_day(
        origin_eva=job.origin_eva,
        dest_eva=job.dest_eva,
        travel_day=day,
        max_transfers=job.max_umstiege,
    )
    allowed = allowed_gattungen(job.train_filter)
    count = 0
    for journey in raw:
        norm = normalize_journey(journey, allowed)
        if norm is None:
            continue
        if norm.planned_departure.date() != day:
            continue
        _upsert_reise(session, job, day, norm)
        count += 1
    return count


def discovery_window(today: date, job: TrackingJob, lookahead_days: int) -> list[date]:
    start = max(today, job.start_date)
    end = min(job.end_date, today + timedelta(days=lookahead_days))
    if start > end:
        return []
    out = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def run_discovery_for_active_jobs() -> None:
    s = get_settings()
    today = date.today()
    with session_scope() as sess:
        jobs = sess.execute(
            select(TrackingJob).where(TrackingJob.status == "active")
        ).scalars().all()
        for job in jobs:
            for day in discovery_window(today, job, s.discovery_lookahead_days):
                try:
                    n = discover_for_job_day(sess, job, day)
                    log.info("discovery job=%s day=%s reisen=%d", job.id, day, n)
                except Exception as exc:
                    log.exception("discovery failed job=%s day=%s: %s", job.id, day, exc)


def mark_completed_jobs() -> None:
    """Move jobs whose end_date is past + all reisen finalized → completed."""
    today = date.today()
    with session_scope() as sess:
        jobs = sess.execute(
            select(TrackingJob).where(
                TrackingJob.status == "active",
                TrackingJob.end_date < today,
            )
        ).scalars().all()
        for job in jobs:
            unfinal = sess.execute(
                select(Reise).where(
                    Reise.job_id == job.id,
                    Reise.finalized_at.is_(None),
                )
            ).first()
            if unfinal is None:
                job.status = "completed"
                log.info("job %s marked completed", job.id)
