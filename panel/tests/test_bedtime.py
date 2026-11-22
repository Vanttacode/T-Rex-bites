import datetime as dt

import pytest

from trexbites_panel import bedtime

S = {**bedtime.DEFAULT_SETTINGS, "enabled": True}
# 2026-11-23 is a Monday
MON = dt.date(2026, 11, 23)


def at(day_offset, hhmm):
    h, m = map(int, hhmm.split(":"))
    return dt.datetime.combine(MON + dt.timedelta(days=day_offset), dt.time(h, m))


@pytest.mark.parametrize("when,expected", [
    (at(0, "06:59"), "off"),   # Monday before school wake (07:00)
    (at(0, "07:00"), "on"),
    (at(0, "20:29"), "on"),
    (at(0, "20:30"), "off"),   # school night
    (at(4, "20:45"), "on"),    # Friday: weekend night starts 21:30
    (at(4, "21:30"), "off"),
    (at(5, "07:30"), "off"),   # Saturday morning: wake 08:00
    (at(5, "08:00"), "on"),
    (at(6, "20:30"), "off"),   # Sunday is a school night
])
def test_bedtime_windows(when, expected):
    assert bedtime.desired_state(when, S, None)[0] == expected


def test_disabled_never_off():
    assert bedtime.desired_state(at(0, "03:00"), {**S, "enabled": False}, None)[0] == "on"


def test_after_midnight_sleep_time():
    late = {**S, "sleep_weekend": "00:30"}
    # Friday night: still on at 23:59 and at 00:15 on Saturday, off at 00:30
    assert bedtime.desired_state(at(4, "23:59"), late, None)[0] == "on"
    assert bedtime.desired_state(at(5, "00:15"), late, None)[0] == "on"
    assert bedtime.desired_state(at(5, "00:30"), late, None)[0] == "off"


def test_reason_and_until():
    state, reason, until = bedtime.desired_state(at(0, "21:00"), S, None)
    assert (state, reason, until) == ("off", "bedtime", at(1, "07:00"))


def test_overrides():
    now = at(0, "15:00")
    off = bedtime.make_override("off", now, S)
    assert bedtime.desired_state(now, S, off) == ("off", "manual", at(1, "07:00"))

    night = at(0, "21:00")
    extra = bedtime.make_override("on", night, S)
    assert bedtime.desired_state(night, S, extra) == ("on", "extra", at(0, "22:00"))
    # after the extra hour, bedtime is back
    assert bedtime.desired_state(at(0, "22:01"), S, extra)[0] == "off"


def test_clean_settings():
    assert bedtime.clean_settings({"enabled": True})["sleep_school"] == "20:30"
    with pytest.raises(ValueError):
        bedtime.clean_settings({"sleep_school": "8pm"})
    with pytest.raises(ValueError):
        bedtime.clean_settings({"sleep_school": "07:00", "wake_school": "07:00"})


class FakeRun:
    def __init__(self, active):
        self.active = set(active)
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args[2:])
        class R:
            stderr = ""
        r = R()
        if args[2] == "is-active":
            r.returncode = 0 if args[-1] in self.active else 3
        else:
            r.returncode = 0
            self.active = {args[-1]}
        return r


def test_tv_power_switches_only_when_needed():
    run = FakeRun(active={"fs42.service"})
    power = bedtime.TVPower(runner=run)
    power.apply("on")
    assert run.calls == [["is-active", "--quiet", "fs42.service"]]
    power.apply("off")
    assert run.calls[-1] == ["start", "trexbites-bedtime.service"]
    assert power.last_error is None
