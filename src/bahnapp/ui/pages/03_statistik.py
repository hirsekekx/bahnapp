"""Page: Statistik pro Job."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from bahnapp.db.models import Reise, ReiseEtappe, Station, TrackingJob
from bahnapp.db.session import session_scope
from bahnapp.ui._shared import gate

gate()
st.title("Statistik")


def _station_name(sess, eva: int) -> str:
    s = sess.get(Station, eva)
    return s.name if s else str(eva)


with session_scope() as sess:
    jobs = sess.execute(select(TrackingJob).order_by(TrackingJob.id.desc())).scalars().all()
    if not jobs:
        st.info("Noch keine Jobs.")
        st.stop()

    job_labels = {
        f"#{j.id} {_station_name(sess, j.origin_eva)} → {_station_name(sess, j.dest_eva)}": j
        for j in jobs
    }
    chosen = st.selectbox("Job", list(job_labels.keys()))
    job = job_labels[chosen]

    reisen = sess.execute(
        select(Reise).where(Reise.job_id == job.id).order_by(Reise.planned_departure)
    ).scalars().all()
    if not reisen:
        st.info("Noch keine Reisen erfasst.")
        st.stop()

    df = pd.DataFrame([{
        "id": r.id,
        "travel_date": r.travel_date,
        "dep_time": r.planned_departure.strftime("%H:%M"),
        "arr_time": r.planned_arrival.strftime("%H:%M"),
        "anzahl_etappen": r.anzahl_etappen,
        "outage_state": r.outage_state,
        "outage_reason": r.outage_reason or "",
        "total_delay_min": r.total_delay_min,
        "finalized": r.finalized_at is not None,
    } for r in reisen])

    finalized = df[df["finalized"]]
    st.subheader("Übersicht")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reisen gesamt", len(df))
    c2.metric("davon abgeschlossen", len(finalized))
    if len(finalized):
        rate = (finalized["outage_state"] == "outage").mean() * 100
        c3.metric("Outage-Quote", f"{rate:.1f} %")
    else:
        c3.metric("Outage-Quote", "—")
    c4.metric("offen", int((df["outage_state"] == "pending").sum()))

    st.subheader("Aufschlüsselung nach Ausfallgrund")
    reasons = finalized[finalized["outage_state"] == "outage"]["outage_reason"].value_counts()
    if reasons.empty:
        st.write("Bisher keine Outages.")
    else:
        st.bar_chart(reasons)

    st.subheader("Heatmap: Tag × Abfahrts-Slot")
    if len(df):
        pivot = df.pivot_table(
            index="dep_time", columns="travel_date", values="outage_state",
            aggfunc=lambda v: v.iloc[0] if len(v) else "",
        ).fillna("")
        # Convert states to numeric codes for color mapping
        code_map = {"on_time": 0, "delayed": 1, "outage": 2, "pending": -1, "": -1}
        z = pivot.applymap(lambda v: code_map.get(v, -1))
        if z.size > 0:
            fig = px.imshow(
                z,
                color_continuous_scale=[
                    (0.0, "#888888"),  # pending/empty
                    (0.25, "#888888"),
                    (0.26, "#2ecc71"),  # on_time
                    (0.5, "#2ecc71"),
                    (0.51, "#f1c40f"),  # delayed
                    (0.75, "#f1c40f"),
                    (0.76, "#e74c3c"),  # outage
                    (1.0, "#e74c3c"),
                ],
                aspect="auto",
                labels=dict(x="Datum", y="Abfahrt", color="Status"),
                zmin=-1, zmax=2,
            )
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Pro Abfahrts-Slot")
    slot_stats = (
        finalized.groupby("dep_time")
        .agg(reisen=("id", "count"),
             outages=("outage_state", lambda s: int((s == "outage").sum())))
    )
    if not slot_stats.empty:
        slot_stats["quote_%"] = (slot_stats["outages"] / slot_stats["reisen"] * 100).round(1)
        st.dataframe(slot_stats, use_container_width=True)

    st.subheader("Etappen-Drilldown (Auslöser)")
    et_rows = []
    for r in reisen:
        if r.outage_state != "outage":
            continue
        ets = sess.execute(
            select(ReiseEtappe).where(ReiseEtappe.reise_id == r.id)
            .order_by(ReiseEtappe.etappe_index)
        ).scalars().all()
        for e in ets:
            if e.origin_status in ("cancelled", "stop_cancelled") or \
               e.dest_status in ("cancelled", "stop_cancelled") or \
               (e.delay_minutes is not None and e.delay_minutes >= 60):
                et_rows.append({
                    "reise_id": r.id,
                    "datum": r.travel_date,
                    "train": e.train_number,
                    "origin_status": e.origin_status,
                    "dest_status": e.dest_status,
                    "delay_min": e.delay_minutes,
                })
    if et_rows:
        et_df = pd.DataFrame(et_rows)
        counts = et_df.groupby("train").size().sort_values(ascending=False)
        st.bar_chart(counts)
        st.dataframe(et_df, use_container_width=True)
    else:
        st.write("Noch keine Outage-Etappen identifiziert.")

    st.subheader("Alle Reisen")
    st.dataframe(df, use_container_width=True)
