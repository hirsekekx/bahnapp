"""Page: neuen Tracking-Job anlegen."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import streamlit as st

from bahnapp.config import get_settings
from bahnapp.db.models import Station, TrackingJob
from bahnapp.db.session import session_scope
from bahnapp.routing.transport_rest import search_locations
from bahnapp.tracker.discovery import discover_for_job_day
from bahnapp.ui._shared import gate

user = gate()
st.title("Neuer Job")

settings = get_settings()


def _station_picker(label: str, key: str) -> dict | None:
    query = st.text_input(label, key=f"q_{key}", placeholder="z.B. Frankfurt(Main)Hbf")
    if not query or len(query) < 3:
        return None
    try:
        results = search_locations(query, results=8)
    except Exception as exc:
        st.error(f"Stationssuche fehlgeschlagen: {exc}")
        return None
    if not results:
        st.info("Keine Treffer")
        return None
    options = {f"{r['name']} ({r['id']})": r for r in results}
    label_choice = st.selectbox(f"Treffer für {label}", list(options.keys()), key=f"sel_{key}")
    return options[label_choice]


col1, col2 = st.columns(2)
with col1:
    origin = _station_picker("Start", "origin")
with col2:
    dest = _station_picker("Ziel", "dest")

today = date.today()
date_col1, date_col2 = st.columns(2)
with date_col1:
    start_date = st.date_input("Beobachten ab", value=today, min_value=today)
with date_col2:
    end_date = st.date_input("Beobachten bis", value=today + timedelta(days=7), min_value=today)

train_filter = st.selectbox("Zug-Filter", ["ICE", "ICE+IC"], index=0)
max_umstiege = st.number_input("Max. Umstiege", min_value=0, max_value=3,
                               value=settings.default_max_umstiege)

if st.button("Job anlegen", type="primary", disabled=not (origin and dest)):
    if origin and dest:
        if origin["id"] == dest["id"]:
            st.error("Start und Ziel müssen sich unterscheiden.")
            st.stop()
        if end_date < start_date:
            st.error("Endedatum darf nicht vor Startdatum liegen.")
            st.stop()
        with session_scope() as sess:
            now = datetime.now()
            for s in (origin, dest):
                if not sess.get(Station, int(s["id"])):
                    sess.add(Station(eva_no=int(s["id"]), name=s["name"], updated_at=now))
            job = TrackingJob(
                origin_eva=int(origin["id"]),
                dest_eva=int(dest["id"]),
                start_date=start_date,
                end_date=end_date,
                train_filter=train_filter,
                max_umstiege=int(max_umstiege),
                status="active",
                created_by=user["email"],
                created_at=now,
            )
            sess.add(job)
            sess.flush()
            job_id = job.id

            preview_day = max(today, start_date)
            try:
                n = discover_for_job_day(sess, job, preview_day)
                st.success(
                    f"Job #{job_id} angelegt. Vorschau-Discovery für {preview_day}: "
                    f"{n} Reisen gefunden."
                )
            except Exception as exc:
                st.warning(f"Job #{job_id} angelegt, Vorschau-Discovery fehlgeschlagen: {exc}")
