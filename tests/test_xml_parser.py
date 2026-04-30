from datetime import datetime

from bahnapp.db_api.timetables import merge_fchg_xml, parse_plan_xml


PLAN_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<timetable station="Frankfurt(Main)Hbf">
  <s id="-12345-1">
    <tl c="ICE" n="691" t="p"/>
    <ar pt="2401151200" pp="7"/>
    <dp pt="2401151205" pp="7"/>
  </s>
  <s id="-12345-2">
    <tl c="ICE" n="377" t="p"/>
    <ar pt="2401151230" pp="9"/>
    <dp pt="2401151232" pp="9"/>
  </s>
</timetable>
"""


FCHG_CANCEL_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<timetable>
  <s id="-12345-1">
    <ar ct="2401151215">
      <m id="m1" t="c"/>
    </ar>
    <dp ct="2401151220">
      <m id="m2" t="c"/>
    </dp>
  </s>
</timetable>
"""


FCHG_DELAY_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<timetable>
  <s id="-12345-2">
    <ar ct="2401151245" pt="2401151230"/>
    <dp ct="2401151247" pt="2401151232"/>
  </s>
</timetable>
"""


def test_parse_plan_basic():
    plan = parse_plan_xml(PLAN_XML, eva_no=8000105)
    assert len(plan) == 2
    ev = plan["-12345-1"]
    assert ev.train_number == "ICE 691"
    assert ev.trip_label == "ICE"
    assert ev.arrival_planned == datetime(2024, 1, 15, 12, 0)
    assert ev.departure_planned == datetime(2024, 1, 15, 12, 5)
    assert not ev.arrival_cancelled


def test_merge_fchg_cancellation():
    plan = parse_plan_xml(PLAN_XML, eva_no=8000105)
    merge_fchg_xml(FCHG_CANCEL_XML, plan)
    ev = plan["-12345-1"]
    assert ev.arrival_cancelled is True
    assert ev.departure_cancelled is True
    assert ev.is_fully_cancelled


def test_merge_fchg_delay():
    plan = parse_plan_xml(PLAN_XML, eva_no=8000105)
    merge_fchg_xml(FCHG_DELAY_XML, plan)
    ev = plan["-12345-2"]
    assert ev.arrival_actual == datetime(2024, 1, 15, 12, 45)
    assert ev.departure_actual == datetime(2024, 1, 15, 12, 47)
    assert not ev.arrival_cancelled
