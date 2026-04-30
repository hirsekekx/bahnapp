"""Convert HAFAS journey JSON (transport.rest) → internal Reise/Etappe records."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class NormalizedEtappe:
    etappe_index: int
    train_number: str            # e.g. "ICE 691"
    gattung: str                 # e.g. "ICE"
    hafas_trip_id: Optional[str]
    origin_eva: int
    dest_eva: int
    origin_planned: datetime
    dest_planned: datetime
    min_umsteige_min: Optional[int] = None  # set on all but the last etappe


@dataclass
class NormalizedReise:
    refresh_token: Optional[str]
    planned_departure: datetime
    planned_arrival: datetime
    etappen: list[NormalizedEtappe] = field(default_factory=list)

    @property
    def anzahl_etappen(self) -> int:
        return len(self.etappen)


_ALLOWED_GATTUNGEN_DEFAULT = {"ICE"}
_GATTUNGEN_ICE_IC = {"ICE", "IC", "EC"}


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    # transport.rest returns ISO with timezone offset; we strip tz to keep
    # comparisons local-time consistent. (DB Timetables uses local time too.)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(tz=None).replace(tzinfo=None)
    return dt


def _gattung_from_leg(leg: dict) -> str:
    line = leg.get("line") or {}
    product = line.get("product") or ""
    name = line.get("name") or ""
    # Normalize: transport.rest uses product like "nationalExpress" (ICE),
    # "national" (IC/EC). Use line name prefix as canonical gattung.
    name_upper = name.upper().strip()
    for token in ("ICE", "EC", "IC", "RE", "RB", "S"):
        if name_upper.startswith(token):
            return token
    if product == "nationalExpress":
        return "ICE"
    if product == "national":
        return "IC"
    return name_upper.split()[0] if name_upper else ""


def _train_number_from_leg(leg: dict, gattung: str) -> str:
    line = leg.get("line") or {}
    fahrt_nr = line.get("fahrtNr") or ""
    if fahrt_nr:
        return f"{gattung} {fahrt_nr}".strip()
    # Fallback to line.name if fahrtNr missing
    name = (line.get("name") or "").strip()
    return name or gattung


def allowed_gattungen(train_filter: str) -> set[str]:
    if train_filter.upper() == "ICE":
        return _ALLOWED_GATTUNGEN_DEFAULT
    if train_filter.upper() in {"ICE+IC", "ICE,IC", "ICE_IC"}:
        return _GATTUNGEN_ICE_IC
    # Fallback: comma-separated
    return {g.strip().upper() for g in train_filter.split(",") if g.strip()}


def normalize_journey(journey: dict, allowed: set[str]) -> Optional[NormalizedReise]:
    """Convert one HAFAS journey to a NormalizedReise.

    Returns None if the journey contains a leg outside `allowed` gattungen
    or if essential fields are missing. Walking-only legs (no `line`) are skipped
    when they are the first/last and short; otherwise they disqualify the journey.
    """
    raw_legs = journey.get("legs") or []
    if not raw_legs:
        return None

    train_legs = []
    for leg in raw_legs:
        if leg.get("walking"):
            # Reject journeys that need walking transfers between trains in V1.
            return None
        line = leg.get("line") or {}
        if not line:
            return None
        gattung = _gattung_from_leg(leg)
        if gattung not in allowed:
            return None
        train_legs.append((leg, gattung))

    if not train_legs:
        return None

    etappen: list[NormalizedEtappe] = []
    for idx, (leg, gattung) in enumerate(train_legs):
        origin = leg.get("origin") or {}
        dest = leg.get("destination") or {}
        origin_id = origin.get("id")
        dest_id = dest.get("id")
        if origin_id is None or dest_id is None:
            return None
        op = _parse_iso(leg.get("plannedDeparture") or leg.get("departure"))
        dp = _parse_iso(leg.get("plannedArrival") or leg.get("arrival"))
        if op is None or dp is None:
            return None
        etappen.append(NormalizedEtappe(
            etappe_index=idx,
            train_number=_train_number_from_leg(leg, gattung),
            gattung=gattung,
            hafas_trip_id=leg.get("tripId"),
            origin_eva=int(origin_id),
            dest_eva=int(dest_id),
            origin_planned=op,
            dest_planned=dp,
        ))

    # Compute min_umsteige_min between consecutive etappen
    for i in range(len(etappen) - 1):
        delta = etappen[i + 1].origin_planned - etappen[i].dest_planned
        etappen[i].min_umsteige_min = max(0, int(delta.total_seconds() // 60))

    return NormalizedReise(
        refresh_token=journey.get("refreshToken"),
        planned_departure=etappen[0].origin_planned,
        planned_arrival=etappen[-1].dest_planned,
        etappen=etappen,
    )


def normalize_journeys(journeys: list[dict], train_filter: str) -> list[NormalizedReise]:
    allowed = allowed_gattungen(train_filter)
    out: list[NormalizedReise] = []
    for j in journeys:
        n = normalize_journey(j, allowed)
        if n is not None:
            out.append(n)
    return out
