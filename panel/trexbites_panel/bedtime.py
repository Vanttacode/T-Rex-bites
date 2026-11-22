"""Bedtime: when every channel goes off and the screen shows "¡A dormir!"."""

import datetime as dt
import logging
import os
import re
import subprocess

log = logging.getLogger("trexbites.bedtime")

DEFAULT_SETTINGS = {
    "enabled": False,
    # the night before a school day (Sunday to Thursday)
    "sleep_school": "20:30",
    # Friday and Saturday nights
    "sleep_weekend": "21:30",
    # Monday to Friday mornings
    "wake_school": "07:00",
    # Saturday and Sunday mornings
    "wake_weekend": "08:00",
}
TIME_KEYS = ("sleep_school", "sleep_weekend", "wake_school", "wake_weekend")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
EXTRA_TIME = dt.timedelta(hours=1)

PLAYER_UNIT = "fs42.service"
BEDTIME_UNIT = "trexbites-bedtime.service"
SETUP_UNIT = "trexbites-setup.service"
# what the screen shows for each state; the units conflict with each other,
# so starting one stops the others
UNITS = {"on": PLAYER_UNIT, "off": BEDTIME_UNIT, "setup": SETUP_UNIT}


def clean_settings(data):
    if not isinstance(data, dict):
        raise ValueError("Configuración inválida.")
    settings = dict(DEFAULT_SETTINGS)
    settings["enabled"] = bool(data.get("enabled", settings["enabled"]))
    for key in TIME_KEYS:
        value = str(data.get(key, settings[key]))
        if not _TIME_RE.match(value):
            raise ValueError("Las horas deben tener el formato HH:MM, por ejemplo 20:30.")
        settings[key] = value
    for kind in ("school", "weekend"):
        if settings[f"sleep_{kind}"] == settings[f"wake_{kind}"]:
            raise ValueError("La hora de dormir y la de despertar no pueden ser iguales.")
    return settings


def _at(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m))


def _night_window(day, settings):
    """The bedtime that starts on the night of `day` and ends the next morning."""
    weekend_night = day.weekday() in (4, 5)  # Friday, Saturday
    sleep = settings["sleep_weekend" if weekend_night else "sleep_school"]
    start = _at(day, sleep)
    if sleep < "12:00":
        # a sleep time like 00:30 belongs to the night that started the day before
        start += dt.timedelta(days=1)
    morning = day + dt.timedelta(days=1)
    wake = settings["wake_weekend" if morning.weekday() in (5, 6) else "wake_school"]
    end = _at(morning, wake)
    return start, end


def current_window(now, settings):
    """(start, end) of the bedtime that contains `now`, or None."""
    for offset in (-1, 0):
        start, end = _night_window(now.date() + dt.timedelta(days=offset), settings)
        if start <= now < end:
            return start, end
    return None


def next_wake(now, settings):
    """When the next bedtime ends: this morning if it's bedtime now, else tomorrow morning."""
    window = current_window(now, settings)
    if window:
        return window[1]
    for offset in (0, 1):
        end = _night_window(now.date() + dt.timedelta(days=offset), settings)[1]
        if end > now:
            return end
    raise AssertionError("unreachable")


def desired_state(now, settings, override):
    """("off" | "on", reason, until) for the TV right now.

    override: {"mode": "off"|"on", "until": epoch seconds} set from the panel, or None.
    """
    if override and override.get("until", 0) > now.timestamp():
        until = dt.datetime.fromtimestamp(override["until"])
        if override.get("mode") == "off":
            return "off", "manual", until
        if override.get("mode") == "on":
            return "on", "extra", until
    if settings.get("enabled"):
        window = current_window(now, settings)
        if window:
            return "off", "bedtime", window[1]
    return "on", None, None


def make_override(mode, now, settings):
    if mode == "off":
        until = next_wake(now, settings)
    elif mode == "on":
        until = now + EXTRA_TIME
    else:
        raise ValueError("Acción inválida.")
    return {"mode": mode, "until": until.timestamp()}


class TVPower:
    """Switches the screen between the TV player, the bedtime picture and the
    WiFi setup instructions, using
    the tv user's systemd services (the panel runs as that same user)."""

    def __init__(self, runner=subprocess.run):
        self._run = runner
        self.last_error = None

    def _systemctl(self, *args):
        uid = os.getuid()
        env = dict(os.environ,
                   XDG_RUNTIME_DIR=f"/run/user/{uid}",
                   DBUS_SESSION_BUS_ADDRESS=f"unix:path=/run/user/{uid}/bus")
        return self._run(["systemctl", "--user", *args], env=env,
                         capture_output=True, text=True, timeout=20)

    def apply(self, state):
        unit = UNITS[state]
        try:
            if self._systemctl("is-active", "--quiet", unit).returncode != 0:
                log.info("switching TV to %s", unit)
                # each unit conflicts with the other, so starting one stops the other
                result = self._systemctl("start", unit)
                if result.returncode != 0:
                    raise RuntimeError(result.stderr.strip() or f"no se pudo iniciar {unit}")
            self.last_error = None
        except (OSError, subprocess.SubprocessError, RuntimeError) as e:
            self.last_error = str(e)
