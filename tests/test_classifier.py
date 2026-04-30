from datetime import datetime

from bahnapp.db_api.timetables import StopEvent
from bahnapp.tracker.classifier import classify_etappe


def _ev(eva, **kw):
    return StopEvent(train_number="ICE 691", trip_label="ICE", eva_no=eva, **kw)


def test_on_time():
    o = _ev(1, departure_planned=datetime(2024, 1, 1, 10, 0),
            departure_actual=datetime(2024, 1, 1, 10, 1))
    d = _ev(2, arrival_planned=datetime(2024, 1, 1, 12, 0),
            arrival_actual=datetime(2024, 1, 1, 12, 2))
    u = classify_etappe(o, d)
    assert u.origin_status == "on_time"
    assert u.dest_status == "on_time"
    assert u.delay_minutes == 2


def test_delayed():
    o = _ev(1, departure_planned=datetime(2024, 1, 1, 10, 0),
            departure_actual=datetime(2024, 1, 1, 10, 8))
    d = _ev(2, arrival_planned=datetime(2024, 1, 1, 12, 0),
            arrival_actual=datetime(2024, 1, 1, 12, 25))
    u = classify_etappe(o, d)
    assert u.origin_status == "delayed"
    assert u.dest_status == "delayed"
    assert u.delay_minutes == 25


def test_full_cancellation():
    o = _ev(1, arrival_cancelled=True, departure_cancelled=True)
    d = _ev(2, arrival_cancelled=True, departure_cancelled=True)
    u = classify_etappe(o, d)
    assert u.origin_status == "cancelled"
    assert u.dest_status == "cancelled"


def test_stop_cancellation_only_at_dest():
    o = _ev(1, departure_planned=datetime(2024, 1, 1, 10, 0),
            departure_actual=datetime(2024, 1, 1, 10, 1))
    d = _ev(2, arrival_cancelled=True, departure_cancelled=True)
    u = classify_etappe(o, d)
    assert u.origin_status == "on_time"
    assert u.dest_status == "stop_cancelled"


def test_no_realtime_data_yet():
    o = _ev(1, departure_planned=datetime(2024, 1, 1, 10, 0))
    d = _ev(2, arrival_planned=datetime(2024, 1, 1, 12, 0))
    u = classify_etappe(o, d)
    assert u.origin_status == "scheduled"
    assert u.dest_status == "scheduled"
    assert u.delay_minutes is None
