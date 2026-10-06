from datetime import date, datetime, time

import pytest

from schedule import Schedule, SlotTaken

MONDAY = date(2026, 10, 12)
SUNDAY = date(2026, 10, 11)
EARLIER = datetime(2026, 10, 1)


@pytest.fixture
def sched(tmp_path):
    return Schedule(tmp_path / "test.db", open_at=time(9), close_at=time(12))


def test_empty_day_has_every_slot_that_fits(sched):
    slots = sched.free_slots(MONDAY, 60, now=EARLIER)
    assert [s.strftime("%H:%M") for s in slots] == ["09:00", "09:30", "10:00", "10:30", "11:00"]


def test_closed_day_and_past_slots(sched):
    assert sched.free_slots(SUNDAY, 30, now=EARLIER) == []
    slots = sched.free_slots(MONDAY, 30, now=datetime(2026, 10, 12, 10, 15))
    assert slots[0].strftime("%H:%M") == "10:30"


def test_booking_blocks_overlapping_slots(sched):
    sched.book(1, "Ann", None, "Haircut", datetime(2026, 10, 12, 10), 60)
    slots = [s.strftime("%H:%M") for s in sched.free_slots(MONDAY, 60, now=EARLIER)]
    assert slots == ["09:00", "11:00"]  # 09:30 and 10:30 would overlap 10:00-11:00


def test_double_booking_is_rejected(sched):
    sched.book(1, "Ann", None, "Haircut", datetime(2026, 10, 12, 10), 60)
    with pytest.raises(SlotTaken):
        sched.book(2, "Bob", None, "Beard", datetime(2026, 10, 12, 10, 30), 30)


def test_cancel_frees_the_slot_and_checks_owner(sched):
    bid = sched.book(1, "Ann", None, "Haircut", datetime(2026, 10, 12, 10), 60)
    assert sched.cancel(bid, user_id=2) is None          # not Bob's booking
    assert sched.cancel(bid, user_id=1)["id"] == bid
    assert len(sched.free_slots(MONDAY, 60, now=EARLIER)) == 5


def test_open_days_skip_closed_weekdays(sched):
    days = sched.open_days(date(2026, 10, 10), 3)  # Sat, (Sun closed), Mon, Tue
    assert [d.isoformat() for d in days] == ["2026-10-10", "2026-10-12", "2026-10-13"]


def test_reminders_sent_once(sched):
    sched.book(1, "Ann", None, "Haircut", datetime(2026, 10, 12, 10), 60)
    now = datetime(2026, 10, 11, 12)
    assert len(sched.due_reminders(now)) == 1
    assert sched.due_reminders(now) == []
