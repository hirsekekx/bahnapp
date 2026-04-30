from datetime import datetime
from types import SimpleNamespace

from bahnapp.tracker.scheduler import (
    BUCKET_MINUTES,
    POLL_PLAN,
    compute_tasks_for_etappe,
    floor_to_bucket,
)


def _etappe(origin_eva, dest_eva, op, dp):
    return SimpleNamespace(
        id=1,
        origin_eva=origin_eva,
        dest_eva=dest_eva,
        origin_planned=op,
        dest_planned=dp,
    )


def test_floor_to_bucket():
    dt = datetime(2024, 1, 1, 10, 17, 42)
    assert floor_to_bucket(dt) == datetime(2024, 1, 1, 10, 15)
    assert floor_to_bucket(datetime(2024, 1, 1, 10, 0)) == datetime(2024, 1, 1, 10, 0)
    assert floor_to_bucket(datetime(2024, 1, 1, 10, 14)) == datetime(2024, 1, 1, 10, 0)
    assert floor_to_bucket(datetime(2024, 1, 1, 10, 30)) == datetime(2024, 1, 1, 10, 30)


def test_six_tasks_per_etappe():
    e = _etappe(1, 2, datetime(2024, 1, 15, 10, 0), datetime(2024, 1, 15, 12, 0))
    tasks = compute_tasks_for_etappe(e)
    assert len(tasks) == len(POLL_PLAN) == 6
    reasons = {t[2] for t in tasks}
    assert reasons == {"pre_dep_60", "pre_dep_5", "post_dep_5",
                       "pre_arr_5", "post_arr_5", "post_arr_30"}


def test_bucket_aligned():
    e = _etappe(1, 2, datetime(2024, 1, 15, 10, 0), datetime(2024, 1, 15, 12, 0))
    for eva, sched, _ in compute_tasks_for_etappe(e):
        assert sched.minute % BUCKET_MINUTES == 0
        assert sched.second == 0
