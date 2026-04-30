from datetime import datetime

from bahnapp.tracker.aggregator import EtappeView, aggregate_reise


def _ev(idx, *, op, dp, oa=None, da=None, os_="on_time", ds="on_time",
        delay=None, umsteige=None):
    return EtappeView(
        etappe_index=idx,
        origin_status=os_,
        dest_status=ds,
        origin_planned=op,
        origin_actual=oa,
        dest_planned=dp,
        dest_actual=da,
        delay_minutes=delay,
        min_umsteige_min=umsteige,
    )


def test_etappe_cancelled_outage():
    e = _ev(0, op=datetime(2024, 1, 1, 10), dp=datetime(2024, 1, 1, 12),
            os_="cancelled", ds="cancelled")
    agg = aggregate_reise([e])
    assert agg.outage_state == "outage"
    assert agg.outage_reason == "etappe_cancelled"
    assert agg.final


def test_stop_cancellation():
    e = _ev(0, op=datetime(2024, 1, 1, 10), dp=datetime(2024, 1, 1, 12),
            os_="on_time", ds="stop_cancelled")
    agg = aggregate_reise([e])
    assert agg.outage_state == "outage"
    assert agg.outage_reason == "stop_cancelled"


def test_arrival_delay_60():
    e = _ev(0, op=datetime(2024, 1, 1, 10), dp=datetime(2024, 1, 1, 12),
            oa=datetime(2024, 1, 1, 10), da=datetime(2024, 1, 1, 13, 5),
            delay=65)
    agg = aggregate_reise([e])
    assert agg.outage_state == "outage"
    assert agg.outage_reason == "arr_delay_60"
    assert agg.total_delay_min == 65


def test_anschluss_verpasst():
    # Etappe 0: ankommt 10 min spät an Umsteigebahnhof; min_umsteige 8 min;
    # Etappe 1: Folgezug fährt planmäßig — Anschluss verpasst.
    e0 = _ev(0,
             op=datetime(2024, 1, 1, 8, 0),
             dp=datetime(2024, 1, 1, 9, 50),
             oa=datetime(2024, 1, 1, 8, 0),
             da=datetime(2024, 1, 1, 10, 0),  # +10 min
             delay=10, umsteige=8)
    e1 = _ev(1,
             op=datetime(2024, 1, 1, 9, 58),
             dp=datetime(2024, 1, 1, 11, 30),
             oa=datetime(2024, 1, 1, 9, 58),
             da=datetime(2024, 1, 1, 11, 30),
             delay=0)
    agg = aggregate_reise([e0, e1])
    assert agg.outage_state == "outage"
    assert agg.outage_reason == "anschluss_verpasst"


def test_anschluss_gehalten_obwohl_verspaetet():
    # Etappe 0: 10 min spät; Etappe 1 wartet → fährt erst um 10:15.
    e0 = _ev(0,
             op=datetime(2024, 1, 1, 8, 0),
             dp=datetime(2024, 1, 1, 9, 50),
             oa=datetime(2024, 1, 1, 8, 0),
             da=datetime(2024, 1, 1, 10, 0),
             delay=10, umsteige=8)
    e1 = _ev(1,
             op=datetime(2024, 1, 1, 9, 58),
             dp=datetime(2024, 1, 1, 11, 30),
             oa=datetime(2024, 1, 1, 10, 15),  # wartete
             da=datetime(2024, 1, 1, 11, 40),
             delay=10, ds="delayed")
    agg = aggregate_reise([e0, e1])
    assert agg.outage_state == "delayed"


def test_on_time_complete():
    e = _ev(0,
            op=datetime(2024, 1, 1, 10),
            dp=datetime(2024, 1, 1, 12),
            oa=datetime(2024, 1, 1, 10),
            da=datetime(2024, 1, 1, 12, 1),
            delay=1)
    agg = aggregate_reise([e])
    assert agg.outage_state == "on_time"
    assert agg.final
