import subprocess

import pytest

from conftest import login
from trexbites_panel import wifi as wifi_module
from trexbites_panel.wifi import HOTSPOT_CON, HOTSPOT_SSID, WifiManager, split_terse


def esc(value):
    return value.replace("\\", "\\\\").replace(":", "\\:")


class FakeNM:
    """A tiny NetworkManager: one WiFi card, optional cable, nearby networks."""

    def __init__(self, ethernet=False, networks=None, passwords=None):
        self.ethernet = ethernet
        self.networks = networks if networks is not None else [("CasaPerez", 80, "WPA2"), ("Vecino:5G", 40, "WPA2")]
        self.passwords = passwords or {"CasaPerez": "clave-secreta"}
        self.connections = {}   # name -> {"ssid", "psk", "mode"}
        self.active = None      # name of the connection on the WiFi card
        self.calls = []

    def __call__(self, args, **kwargs):
        assert args[0] == "nmcli"
        args = args[1:]
        self.calls.append(args)
        out, rc = "", 0
        if args[:1] == ["-t"]:
            args = args[1:]
        if args[:1] == ["--wait"]:
            args = args[2:]
        if args[:2] == ["-f", "DEVICE,TYPE,STATE,CONNECTION"]:
            lines = ["wlp2s0:wifi:%s:%s" % (("connected", esc(self.active)) if self.active else ("disconnected", ""))]
            lines.append("enp1s0:ethernet:%s" % ("connected:Cable" if self.ethernet else "unavailable:"))
            out = "\n".join(lines)
        elif args[:2] == ["-f", "NAME,TYPE"]:
            out = "\n".join(f"{esc(n)}:802-11-wireless" for n in self.connections)
        elif args[:2] == ["-f", "NAME"]:
            out = "\n".join(esc(n) for n in self.connections)
        elif args[:2] == ["-f", "IP4.ADDRESS"]:
            out = "IP4.ADDRESS[1]:192.168.1.50/24"
        elif args[:2] == ["-f", "SSID,SIGNAL,SECURITY"]:
            if self.active == HOTSPOT_CON:
                out = ""  # the card can't scan while it is the hotspot
            else:
                out = "\n".join(f"{esc(s)}:{sig}:{sec}" for s, sig, sec in self.networks)
        elif args[:3] == ["device", "wifi", "rescan"]:
            pass
        elif args[:2] == ["connection", "add"]:
            opts = dict(zip(args[2::2], args[3::2]))
            self.connections[opts["con-name"]] = {
                "ssid": opts["ssid"], "psk": opts.get("wifi-sec.psk", ""),
                "mode": opts.get("802-11-wireless.mode", "infrastructure"),
            }
        elif args[:2] == ["connection", "delete"]:
            self.connections.pop(args[2], None)
            if self.active == args[2]:
                self.active = None
        elif args[:2] == ["connection", "down"]:
            if self.active == args[2]:
                self.active = None
        elif args[:2] == ["connection", "up"]:
            con = self.connections.get(args[2])
            if con is None:
                rc = 10
            elif con["mode"] == "ap":
                self.active = args[2]
            elif any(s == con["ssid"] for s, _, _ in self.networks) and \
                    self.passwords.get(con["ssid"], "") == con["psk"]:
                self.active = args[2]
            else:
                rc = 4
        return subprocess.CompletedProcess(args, rc, out, "")


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(wifi_module.time, "sleep", lambda s: None)


def test_split_terse_handles_escaped_colons():
    assert split_terse(r"Vecino\:5G:40:WPA2") == ["Vecino:5G", "40", "WPA2"]
    assert split_terse(r"a\\b:c") == ["a\\b", "c"]


def test_first_start_opens_setup_network_and_shows_setup_screen():
    nm, clock = FakeNM(), Clock()
    w = WifiManager(runner=nm, clock=clock)
    w.tick()
    assert not w.needs_setup and nm.active is None  # waits a few seconds first
    clock.now = 25
    w.tick()
    assert nm.active == HOTSPOT_CON
    assert nm.connections[HOTSPOT_CON]["ssid"] == HOTSPOT_SSID
    assert w.needs_setup is True
    # the list of networks was taken before the card became the hotspot
    assert [n["ssid"] for n in w.networks] == ["CasaPerez", "Vecino:5G"]


def test_connect_to_home_wifi():
    nm, clock = FakeNM(), Clock()
    w = WifiManager(runner=nm, clock=clock)
    clock.now = 25
    w.tick(); w.tick()
    w.connect("CasaPerez", "clave-secreta")
    assert nm.active == "Casa - CasaPerez"
    assert w.last_error is None and w.needs_setup is False
    w.tick()
    assert w.just_connected is True
    assert w.status_cache["ssid"] == "CasaPerez"
    assert w.status_cache["ip"] == "192.168.1.50"


def test_wrong_password_reopens_setup_network():
    nm, clock = FakeNM(), Clock()
    w = WifiManager(runner=nm, clock=clock)
    clock.now = 25
    w.tick(); w.tick()
    w.connect("CasaPerez", "equivocada")
    assert "Revisa la clave" in w.last_error
    assert "Casa - CasaPerez" not in nm.connections
    assert nm.active == HOTSPOT_CON


def test_cable_means_no_setup_network():
    nm, clock = FakeNM(ethernet=True), Clock()
    w = WifiManager(runner=nm, clock=clock)
    clock.now = 500
    w.tick()
    assert nm.active is None and w.needs_setup is False
    assert w.status_cache["connected"] is True


def test_router_off_keeps_tv_playing_and_retries_home_network():
    nm, clock = FakeNM(), Clock()
    nm.connections["Casa - CasaPerez"] = {"ssid": "CasaPerez", "psk": "clave-secreta", "mode": "infrastructure"}
    nm.networks = []  # router is off
    w = WifiManager(runner=nm, clock=clock)
    w.tick()
    clock.now = 30
    w.tick()
    assert nm.active is None  # a saved network: wait longer before the setup network
    clock.now = 100
    w.tick()
    assert nm.active == HOTSPOT_CON
    assert w.needs_setup is False  # the TV keeps playing
    # a while later the setup network closes so the box can look for home again
    clock.now = 100 + wifi_module.RETRY_HOME_EVERY
    w.tick()
    assert nm.active is None


def test_validate_wifi_input():
    with pytest.raises(ValueError):
        wifi_module.validate("", "")
    with pytest.raises(ValueError):
        wifi_module.validate("Casa", "corta")
    assert wifi_module.validate("Abierta", "") == ("Abierta", "")


# ---------- panel API ----------

def test_wifi_api_requires_pin(env):
    c = env["client"]
    assert c.get("/api/wifi").status_code == 401
    assert c.post("/api/wifi/connect", json={"ssid": "x", "password": "12345678"}).status_code == 401


def test_wifi_api_status_and_validation(env):
    c = env["client"]
    login(c)
    w = env["module"].app.state.wifi
    w.networks = [{"ssid": "CasaPerez", "signal": 80, "secure": True}]
    w.status_cache = {"has_wifi": True, "connected": False, "hotspot": True}
    data = c.get("/api/wifi").json()
    assert data["networks"][0]["ssid"] == "CasaPerez"
    assert data["hotspot"] is True
    assert c.post("/api/wifi/connect", json={"ssid": "CasaPerez", "password": "corta"}).status_code == 400
    assert c.post("/api/wifi/connect", json={"ssid": "CasaPerez", "password": "clave-secreta"}).status_code == 200


def test_setup_screen_replaces_tv_when_wifi_needs_setup(env):
    c = env["client"]
    login(c)
    env["module"].app.state.wifi.needs_setup = True
    assert c.get("/api/status").json()["power"]["state"] == "on"  # not recomputed yet
    power = c.get("/api/bedtime").json()["power"]
    assert (power["state"], power["reason"]) == ("setup", "wifi")


def test_captive_portal_redirects_unknown_pages(env):
    c = env["client"]
    w = env["module"].app.state.wifi
    w.status_cache = {"hotspot": True}
    resp = c.get("/generate_204", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "http://10.42.0.1/"
    w.status_cache = {"hotspot": False}
    assert c.get("/hotspot-detect.html", follow_redirects=False).headers["location"] == "/"
    # API errors stay JSON
    assert c.get("/api/nope").status_code == 404
