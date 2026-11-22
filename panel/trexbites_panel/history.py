"""What the TV played each day, sampled once a minute from the player status."""

import datetime as dt
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    day TEXT NOT NULL,
    channel INTEGER,
    network TEXT NOT NULL,
    title TEXT NOT NULL,
    minutes INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, network, title)
)
"""
KEEP_DAYS = 90


class History:

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            with conn:  # commits on success
                yield conn
        finally:
            conn.close()

    def record_minute(self, when, status):
        """Count one minute of whatever the player reports as playing."""
        if not isinstance(status, dict) or status.get("status") != "playing":
            return
        title = str(status.get("title") or "").strip()
        network = str(status.get("network_name") or "").strip()
        if not title or not network or title.startswith("_"):
            return
        day = when.date().isoformat()
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO plays (day, channel, network, title, minutes) VALUES (?, ?, ?, ?, 1) "
                "ON CONFLICT(day, network, title) DO UPDATE SET minutes = minutes + 1, channel = excluded.channel",
                (day, status.get("channel_number"), network, title[:200]),
            )
            cutoff = (when.date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
            db.execute("DELETE FROM plays WHERE day < ?", (cutoff,))

    def summary(self, today, days=7):
        first = (today - dt.timedelta(days=days - 1)).isoformat()
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT day, channel, network, title, minutes FROM plays WHERE day >= ? "
                "ORDER BY day DESC, minutes DESC", (first,),
            ).fetchall()
        by_day = {}
        for day, channel, network, title, minutes in rows:
            entry = by_day.setdefault(day, {"day": day, "total_minutes": 0, "programs": []})
            entry["total_minutes"] += minutes
            entry["programs"].append({"channel": channel, "network": network, "title": title, "minutes": minutes})
        result = []
        for offset in range(days):
            day = (today - dt.timedelta(days=offset)).isoformat()
            result.append(by_day.get(day, {"day": day, "total_minutes": 0, "programs": []}))
        return result
