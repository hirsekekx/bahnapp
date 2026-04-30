from datetime import datetime

from bahnapp.routing.normalize import allowed_gattungen, normalize_journey


def _journey(legs):
    return {"refreshToken": "tok", "legs": legs}


def _leg(name, fahrt, origin, dest, dep, arr, product="nationalExpress",
         walking=False, trip_id="trip-1"):
    if walking:
        return {"walking": True, "origin": {"id": origin}, "destination": {"id": dest}}
    return {
        "tripId": trip_id,
        "origin": {"id": str(origin), "name": "O"},
        "destination": {"id": str(dest), "name": "D"},
        "plannedDeparture": dep,
        "plannedArrival": arr,
        "line": {"name": name, "fahrtNr": fahrt, "product": product},
    }


def test_direct_ice():
    j = _journey([
        _leg("ICE 691", "691", 8000105, 8011160,
             "2024-01-15T10:00:00+01:00", "2024-01-15T14:00:00+01:00"),
    ])
    n = normalize_journey(j, allowed_gattungen("ICE"))
    assert n is not None
    assert n.anzahl_etappen == 1
    e = n.etappen[0]
    assert e.train_number == "ICE 691"
    assert e.gattung == "ICE"
    assert e.origin_eva == 8000105
    assert e.dest_eva == 8011160
    assert e.min_umsteige_min is None


def test_two_legs_with_transfer():
    j = _journey([
        _leg("ICE 691", "691", 8000105, 8000260,
             "2024-01-15T10:00:00+01:00", "2024-01-15T11:30:00+01:00"),
        _leg("ICE 1577", "1577", 8000260, 8002549,
             "2024-01-15T11:42:00+01:00", "2024-01-15T13:00:00+01:00"),
    ])
    n = normalize_journey(j, allowed_gattungen("ICE"))
    assert n is not None
    assert n.anzahl_etappen == 2
    assert n.etappen[0].min_umsteige_min == 12
    assert n.etappen[1].min_umsteige_min is None


def test_walking_leg_rejected():
    j = _journey([
        _leg("ICE 691", "691", 8000105, 8000260,
             "2024-01-15T10:00:00+01:00", "2024-01-15T11:30:00+01:00"),
        _leg(None, None, 8000260, 8000260,
             None, None, walking=True),
        _leg("ICE 1577", "1577", 8000260, 8002549,
             "2024-01-15T11:42:00+01:00", "2024-01-15T13:00:00+01:00"),
    ])
    assert normalize_journey(j, allowed_gattungen("ICE")) is None


def test_ice_only_filter_rejects_ic():
    j = _journey([
        _leg("IC 2007", "2007", 8000105, 8011160,
             "2024-01-15T10:00:00+01:00", "2024-01-15T14:00:00+01:00",
             product="national"),
    ])
    assert normalize_journey(j, allowed_gattungen("ICE")) is None


def test_ice_ic_filter_accepts_ic():
    j = _journey([
        _leg("IC 2007", "2007", 8000105, 8011160,
             "2024-01-15T10:00:00+01:00", "2024-01-15T14:00:00+01:00",
             product="national"),
    ])
    n = normalize_journey(j, allowed_gattungen("ICE+IC"))
    assert n is not None
    assert n.etappen[0].gattung == "IC"
