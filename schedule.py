"""Booking storage and slot logic. No Telegram code here, so it is easy to test."""

import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta

SLOT_MINUTES = 30


class SlotTaken(Exception):
    pass


class Schedule:
    def __init__(self, path, open_at=time(9), close_at=time(18), closed_weekdays=(6,)):
        self.path = path
        self.open_at = open_at
        self.close_at = close_at
        self.closed_weekdays = set(closed_weekdays)  # Monday = 0, Sunday = 6
        with closing(self._connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    user_name TEXT,
                    phone TEXT,
                    service TEXT NOT NULL,
                    starts_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    cancelled INTEGER NOT NULL DEFAULT 0
                )""")
            db.execute("CREATE INDEX IF NOT EXISTS idx_start ON bookings(starts_at)")

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None)  # explicit transactions
        db.row_factory = sqlite3.Row
        return db

    def is_open(self, day):
        return day.weekday() not in self.closed_weekdays

    def open_days(self, start, count):
        days, day = [], start
        while len(days) < count:
            if self.is_open(day):
                days.append(day)
            day += timedelta(days=1)
        return days

    def _busy(self, db, day):
        rows = db.execute(
            "SELECT starts_at, ends_at FROM bookings "
            "WHERE cancelled = 0 AND starts_at < ? AND ends_at > ?",
            (datetime.combine(day + timedelta(days=1), time()).isoformat(),
             datetime.combine(day, time()).isoformat()))
        return [(datetime.fromisoformat(r[0]), datetime.fromisoformat(r[1])) for r in rows]

    def free_slots(self, day, minutes, now=None):
        """Start times on `day` where a `minutes`-long appointment fits."""
        if not self.is_open(day):
            return []
        now = now or datetime.now()
        with closing(self._connect()) as db:
            busy = self._busy(db, day)
        slots = []
        start = datetime.combine(day, self.open_at)
        close = datetime.combine(day, self.close_at)
        while start + timedelta(minutes=minutes) <= close:
            end = start + timedelta(minutes=minutes)
            if start > now and not any(s < end and start < e for s, e in busy):
                slots.append(start)
            start += timedelta(minutes=SLOT_MINUTES)
        return slots

    def book(self, user_id, user_name, phone, service, starts_at, minutes):
        """Insert a booking; raise SlotTaken if someone got there first."""
        ends_at = starts_at + timedelta(minutes=minutes)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")  # lock so two users can't grab one slot
            try:
                clash = db.execute(
                    "SELECT 1 FROM bookings WHERE cancelled = 0 AND starts_at < ? AND ends_at > ?",
                    (ends_at.isoformat(), starts_at.isoformat())).fetchone()
                if clash:
                    raise SlotTaken(starts_at)
                cur = db.execute(
                    "INSERT INTO bookings (user_id, user_name, phone, service, starts_at, ends_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (user_id, user_name, phone, service, starts_at.isoformat(), ends_at.isoformat()))
                db.execute("COMMIT")
                return cur.lastrowid
            except Exception:
                db.execute("ROLLBACK")
                raise

    def upcoming_for_user(self, user_id, now=None):
        now = now or datetime.now()
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM bookings WHERE user_id = ? AND cancelled = 0 AND starts_at > ? "
                "ORDER BY starts_at", (user_id, now.isoformat()))]

    def cancel(self, booking_id, user_id):
        """Cancel the user's own booking. Returns the booking or None."""
        with closing(self._connect()) as db, db:
            row = db.execute("SELECT * FROM bookings WHERE id = ? AND user_id = ? AND cancelled = 0",
                             (booking_id, user_id)).fetchone()
            if row:
                db.execute("UPDATE bookings SET cancelled = 1 WHERE id = ?", (booking_id,))
            return dict(row) if row else None

    def day_agenda(self, day):
        with closing(self._connect()) as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM bookings WHERE cancelled = 0 AND starts_at >= ? AND starts_at < ? "
                "ORDER BY starts_at",
                (datetime.combine(day, time()).isoformat(),
                 datetime.combine(day + timedelta(days=1), time()).isoformat()))]

    def due_reminders(self, now, hours_ahead=24):
        """Bookings starting within the next `hours_ahead` hours that haven't been reminded."""
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS reminded (booking_id INTEGER PRIMARY KEY)")
            rows = [dict(r) for r in db.execute(
                "SELECT * FROM bookings WHERE cancelled = 0 AND starts_at > ? AND starts_at <= ? "
                "AND id NOT IN (SELECT booking_id FROM reminded)",
                (now.isoformat(), (now + timedelta(hours=hours_ahead)).isoformat()))]
            db.executemany("INSERT INTO reminded VALUES (?)", [(r["id"],) for r in rows])
            return rows
