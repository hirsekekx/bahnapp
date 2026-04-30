from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


OUTAGE_STATE = Enum("pending", "on_time", "delayed", "outage", name="outage_state")
ETAPPE_STATUS = Enum(
    "scheduled", "on_time", "delayed", "stop_cancelled", "cancelled", name="etappe_status"
)
JOB_STATUS = Enum("active", "paused", "completed", name="job_status")
POLL_REASON = Enum(
    "pre_dep_60", "pre_dep_5", "post_dep_5", "pre_arr_5", "post_arr_5", "post_arr_30",
    name="poll_reason",
)
POLL_STATUS = Enum("pending", "done", "failed", name="poll_status")


class Station(Base):
    __tablename__ = "stations"

    eva_no: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    ds100: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TrackingJob(Base):
    __tablename__ = "tracking_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    origin_eva: Mapped[int] = mapped_column(BigInteger, ForeignKey("stations.eva_no"))
    dest_eva: Mapped[int] = mapped_column(BigInteger, ForeignKey("stations.eva_no"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    train_filter: Mapped[str] = mapped_column(String(32), default="ICE")
    max_umstiege: Mapped[int] = mapped_column(SmallInteger, default=2)
    status: Mapped[str] = mapped_column(JOB_STATUS, default="active")
    created_by: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime)

    reisen: Mapped[list[Reise]] = relationship(back_populates="job", cascade="all, delete-orphan")


class Reise(Base):
    __tablename__ = "reisen"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "travel_date", "planned_departure", "anzahl_etappen",
            name="uniq_job_reise",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tracking_jobs.id", ondelete="CASCADE")
    )
    travel_date: Mapped[date] = mapped_column(Date)
    refresh_token: Mapped[str | None] = mapped_column(String(512), nullable=True)
    planned_departure: Mapped[datetime] = mapped_column(DateTime)
    planned_arrival: Mapped[datetime] = mapped_column(DateTime)
    anzahl_etappen: Mapped[int] = mapped_column(SmallInteger)
    outage_state: Mapped[str] = mapped_column(OUTAGE_STATE, default="pending")
    outage_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_delay_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime)

    job: Mapped[TrackingJob] = relationship(back_populates="reisen")
    etappen: Mapped[list[ReiseEtappe]] = relationship(
        back_populates="reise", cascade="all, delete-orphan", order_by="ReiseEtappe.etappe_index"
    )


class ReiseEtappe(Base):
    __tablename__ = "reise_etappen"
    __table_args__ = (
        UniqueConstraint("reise_id", "etappe_index", name="uniq_reise_etappe"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    reise_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reisen.id", ondelete="CASCADE")
    )
    etappe_index: Mapped[int] = mapped_column(SmallInteger)
    train_number: Mapped[str] = mapped_column(String(32))
    hafas_trip_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    origin_eva: Mapped[int] = mapped_column(BigInteger)
    dest_eva: Mapped[int] = mapped_column(BigInteger)
    origin_planned: Mapped[datetime] = mapped_column(DateTime)
    origin_actual: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    origin_status: Mapped[str] = mapped_column(ETAPPE_STATUS, default="scheduled")
    dest_planned: Mapped[datetime] = mapped_column(DateTime)
    dest_actual: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    dest_status: Mapped[str] = mapped_column(ETAPPE_STATUS, default="scheduled")
    delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    min_umsteige_min: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    raw_messages: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(DateTime)

    reise: Mapped[Reise] = relationship(back_populates="etappen")


class PollTask(Base):
    __tablename__ = "poll_tasks"
    __table_args__ = (
        UniqueConstraint("eva_no", "scheduled_at", "reason", name="uniq_eva_bucket_reason"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    eva_no: Mapped[int] = mapped_column(BigInteger)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    reason: Mapped[str] = mapped_column(POLL_REASON)
    status: Mapped[str] = mapped_column(POLL_STATUS, default="pending")
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, default=0)


class PollTaskEtappe(Base):
    __tablename__ = "poll_task_etappen"

    poll_task_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("poll_tasks.id", ondelete="CASCADE"), primary_key=True
    )
    etappe_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("reise_etappen.id", ondelete="CASCADE"), primary_key=True
    )
