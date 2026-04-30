"""Page: aktive und abgeschlossene Tracking-Jobs verwalten."""
from __future__ import annotations

import streamlit as st
from sqlalchemy import func, select

from bahnapp.db.models import Reise, Station, TrackingJob
from bahnapp.db.session import session_scope
from bahnapp.ui._shared import gate

gate()
st.title("Aktive Jobs")


def _station_name(sess, eva: int) -> str:
    s = sess.get(Station, eva)
    return s.name if s else str(eva)


with session_scope() as sess:
    jobs = sess.execute(
        select(TrackingJob).order_by(TrackingJob.created_at.desc())
    ).scalars().all()

    if not jobs:
        st.info("Noch keine Jobs angelegt.")
        st.stop()

    for job in jobs:
        with st.container(border=True):
            origin = _station_name(sess, job.origin_eva)
            dest = _station_name(sess, job.dest_eva)
            st.subheader(f"#{job.id} — {origin} → {dest}")
            st.caption(
                f"{job.start_date} bis {job.end_date} | Filter {job.train_filter} | "
                f"max {job.max_umstiege} Umstiege | Status: **{job.status}** | "
                f"angelegt von {job.created_by}"
            )

            counts = sess.execute(
                select(Reise.outage_state, func.count(Reise.id))
                .where(Reise.job_id == job.id)
                .group_by(Reise.outage_state)
            ).all()
            count_map = {row[0]: row[1] for row in counts}
            outage_count = count_map.get("outage", 0)
            on_time = count_map.get("on_time", 0)
            delayed = count_map.get("delayed", 0)
            pending = count_map.get("pending", 0)

            anschluss_verpasst = sess.execute(
                select(func.count(Reise.id)).where(
                    Reise.job_id == job.id,
                    Reise.outage_reason == "anschluss_verpasst",
                )
            ).scalar() or 0

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("on_time", on_time)
            c2.metric("delayed", delayed)
            c3.metric("outage", outage_count)
            c4.metric("davon Anschluss verpasst", anschluss_verpasst)
            c5.metric("pending", pending)

            cols = st.columns(3)
            if job.status == "active":
                if cols[0].button("Pausieren", key=f"pause_{job.id}"):
                    job.status = "paused"
                    st.rerun()
            elif job.status == "paused":
                if cols[0].button("Fortsetzen", key=f"resume_{job.id}"):
                    job.status = "active"
                    st.rerun()
            if cols[2].button("Löschen", key=f"del_{job.id}"):
                sess.delete(job)
                st.rerun()
