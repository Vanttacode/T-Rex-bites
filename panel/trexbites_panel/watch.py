"""Watch a channel on another screen (a phone, a tablet, another TV's browser).

Reads FieldStation42's schedule database to find what a channel is showing
right now, and from which second, so the browser plays it in sync with the
"real" TV schedule, commercials included.
"""

import datetime as dt
import json
import sqlite3
from pathlib import Path

DB_RELATIVE = "runtime/fs42_fluid.db"


def _parse(ts):
    if isinstance(ts, dt.datetime):
        return ts
    try:
        return dt.datetime.fromisoformat(str(ts))
    except ValueError:
        return None


def db_path(fs42_dir):
    try:
        conf = json.loads((Path(fs42_dir) / "confs" / "main_config.json").read_text())
        custom = conf.get("db_path")
    except (OSError, ValueError):
        custom = None
    path = Path(custom or DB_RELATIVE)
    return path if path.is_absolute() else Path(fs42_dir) / path


def now_playing(fs42_dir, network_name, now=None):
    """{"path", "offset", "duration", "title", "content_type", "remaining"} or None
    when the channel has nothing scheduled now (off the air)."""
    now = now or dt.datetime.now()
    path = db_path(fs42_dir)
    if not path.is_file():
        return None
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute(
                "SELECT start_time, end_time, title, plan_json FROM liquid_blocks "
                "WHERE station = ? AND start_time <= ? AND end_time > ? ORDER BY start_time DESC LIMIT 1",
                (network_name, stamp, stamp)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    if not rows:
        return None
    start_s, end_s, title, plan_json = rows[0]
    start = _parse(start_s)
    if start is None:
        return None
    try:
        plan = json.loads(plan_json or "[]")
    except ValueError:
        return None
    elapsed = (now - start).total_seconds()
    for entry in plan:
        duration = float(entry.get("duration") or 0)
        if duration <= 0:
            continue
        if elapsed < duration:
            return {
                "path": entry.get("path"),
                "offset": round(float(entry.get("skip") or 0) + elapsed, 2),
                "duration": duration,
                "remaining": round(duration - elapsed, 2),
                "title": title,
                "content_type": entry.get("content_type", "feature"),
                "is_stream": bool(entry.get("is_stream")),
            }
        elapsed -= duration
    return None


def resolve_media(fs42_dir, media_path, allowed_roots):
    """The file to send to the browser, only if it lives in a media folder."""
    if not media_path:
        return None
    path = Path(media_path)
    if not path.is_absolute():
        path = Path(fs42_dir) / path
    try:
        path = path.resolve()
    except OSError:
        return None
    for root in allowed_roots:
        try:
            root = Path(root).resolve()
        except OSError:
            continue
        if path == root or root in path.parents:
            return path if path.is_file() else None
    return None
