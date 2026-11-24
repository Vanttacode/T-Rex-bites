"""WiFi setup without a keyboard or a router cable.

When the TV box has no network, it opens its own open WiFi network
("T-Rex Bites Config"). A phone joins it, the setup page opens by itself
(captive portal) and the person picks the home WiFi and types its password.
Everything goes through NetworkManager's nmcli; the panel's user may manage
connections thanks to a polkit rule installed with T-Rex Bites.
"""

import json
import logging
import subprocess
import time
from pathlib import Path

log = logging.getLogger("trexbites.wifi")

HOTSPOT_CON = "TRexBites-Config"
HOTSPOT_SSID = "T-Rex Bites Config"
# NetworkManager's address for shared (hotspot) networks
HOTSPOT_IP = "10.42.0.1"
HOME_PREFIX = "Casa - "
# how long the box waits before opening the setup network: short the first time,
# longer when a home network is saved (the router may just be restarting)
FIRST_SETUP_GRACE = 20
OFFLINE_GRACE = 90
# with a saved home network, the setup network closes now and then so the box
# can look for the home network again (the WiFi chip can't do both at once)
RETRY_HOME_EVERY = 300
CONNECT_TIMEOUT = 45
# after the setup network fails to open (a WiFi chip that can't be an access
# point), wait this long before trying again
HOTSPOT_RETRY_AFTER = 300
# the on-screen setup (setup_screen.py) marks itself busy while it scans or
# connects; the panel leaves the WiFi card alone meanwhile
BUSY_MAX_AGE = 120


def split_terse(line):
    """Split one line of `nmcli -t` output: fields are separated by ':' and
    a literal ':' or '\\' inside a value is escaped with a backslash."""
    fields, current, escaped = [], [], False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def validate(ssid, password):
    if not isinstance(ssid, str) or not ssid.strip():
        raise ValueError("Elige una red WiFi.")
    if len(ssid.encode()) > 32:
        raise ValueError("El nombre de la red es demasiado largo.")
    password = password or ""
    if password and not 8 <= len(password) <= 63:
        raise ValueError("La clave del WiFi debe tener entre 8 y 63 caracteres.")
    return ssid, password


class WifiManager:

    def __init__(self, runner=subprocess.run, clock=time.monotonic, state_dir=None):
        self._run = runner
        self._clock = clock
        # shared with the on-screen setup: network list and setup-network state
        self._state_dir = Path(state_dir) if state_dir else None
        self._hotspot_retry_at = 0.0
        self.networks = []          # last scan, kept while the setup network is on
        self.last_error = None
        self.last_connected = None  # name of the home network that worked last
        self.connecting = False
        self.needs_setup = False    # True: show the setup screen instead of the TV
        self.hotspot_error = None   # why the setup network could not open, if it failed
        self.status_cache = {}
        self._offline_since = None
        self._hotspot_since = None
        self._was_online = False
        self.just_connected = False  # set once when the box gets online

    # ---------- nmcli ----------

    def nm(self, *args, timeout=20):
        return self._run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)

    def _rows(self, *args, timeout=20):
        result = self.nm("-t", *args, timeout=timeout)
        if result.returncode != 0:
            return []
        return [split_terse(line) for line in result.stdout.splitlines() if line]

    def devices(self):
        """[(device, type, state, connection)]"""
        return [tuple((row + ["", "", "", ""])[:4])
                for row in self._rows("-f", "DEVICE,TYPE,STATE,CONNECTION", "device")]

    def wifi_device(self):
        for dev, dtype, _, _ in self.devices():
            if dtype == "wifi":
                return dev
        return None

    def saved_home_networks(self):
        return [row[0] for row in self._rows("-f", "NAME,TYPE", "connection", "show")
                if len(row) > 1 and row[1] == "802-11-wireless" and row[0] != HOTSPOT_CON]

    # ---------- state ----------

    def status(self):
        wifi_dev, wifi_con, ethernet, hotspot, online_dev = None, None, False, False, None
        for dev, dtype, state, con in self.devices():
            if dtype == "wifi":
                wifi_dev = dev
                if state == "connected":
                    if con == HOTSPOT_CON:
                        hotspot = True
                    else:
                        wifi_con = con
                        online_dev = dev
            elif dtype == "ethernet" and state == "connected":
                ethernet = True
                online_dev = online_dev or dev
        ip = None
        if online_dev:
            for row in self._rows("-f", "IP4.ADDRESS", "device", "show", online_dev):
                if row and row[-1]:
                    ip = row[-1].split("/")[0]
                    break
        ssid = wifi_con[len(HOME_PREFIX):] if wifi_con and wifi_con.startswith(HOME_PREFIX) else wifi_con
        return {
            "has_wifi": wifi_dev is not None,
            "connected": bool(wifi_con or ethernet),
            "ssid": ssid,
            "ethernet": ethernet,
            "ip": ip,
            "hotspot": hotspot,
            "hotspot_ssid": HOTSPOT_SSID,
            "hotspot_ip": HOTSPOT_IP,
        }

    def scan(self, rescan=True):
        if rescan:
            self.nm("device", "wifi", "rescan", timeout=30)
            time.sleep(3)
        best = {}
        for row in self._rows("-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", timeout=30):
            if len(row) < 3 or not row[0] or row[0] == HOTSPOT_SSID:
                continue
            ssid, signal, security = row[0], row[1], row[2]
            signal = int(signal) if signal.isdigit() else 0
            if ssid not in best or signal > best[ssid]["signal"]:
                best[ssid] = {"ssid": ssid, "signal": signal, "secure": security not in ("", "--")}
        self.networks = sorted(best.values(), key=lambda n: -n["signal"])
        return self.networks

    # ---------- setup network ----------

    def start_hotspot(self, device):
        # most WiFi chips can't search for networks while they are the hotspot:
        # look first, and show this list on the setup page
        try:
            self.scan()
        except subprocess.SubprocessError:
            pass
        if HOTSPOT_CON not in [r[0] for r in self._rows("-f", "NAME", "connection", "show")]:
            self.nm("connection", "add", "type", "wifi", "ifname", device, "con-name", HOTSPOT_CON,
                    "autoconnect", "no", "ssid", HOTSPOT_SSID,
                    "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
                    "ipv4.method", "shared", "ipv4.addresses", f"{HOTSPOT_IP}/24",
                    "ipv6.method", "ignore")
        result = self.nm("connection", "up", HOTSPOT_CON, timeout=40)
        if result.returncode != 0:
            # usually a WiFi chip that can't act as an access point
            self.hotspot_error = result.stderr.strip() or "nmcli connection up failed"
            self._hotspot_retry_at = self._clock() + HOTSPOT_RETRY_AFTER
            log.warning("could not start the setup network: %s", self.hotspot_error)
        else:
            log.info("setup network %r is on", HOTSPOT_SSID)

    def stop_hotspot(self):
        self.nm("connection", "down", HOTSPOT_CON, timeout=30)

    # ---------- connecting to the home WiFi ----------

    def connect(self, ssid, password):
        """Blocking: save the home network, leave setup mode and join it.
        On failure the profile is removed and the setup network comes back."""
        ssid, password = validate(ssid, password)
        name = f"{HOME_PREFIX}{ssid}"
        self.connecting = True
        self.last_error = None
        try:
            device = self.wifi_device()
            if not device:
                raise RuntimeError("Este equipo no tiene WiFi.")
            self.nm("connection", "delete", name)
            args = ["connection", "add", "type", "wifi", "ifname", device, "con-name", name,
                    "ssid", ssid, "connection.autoconnect", "yes"]
            if password:
                args += ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password]
            added = self.nm(*args)
            if added.returncode != 0:
                raise RuntimeError("No se pudo guardar la red.")
            self.stop_hotspot()
            up = self.nm("--wait", str(CONNECT_TIMEOUT), "connection", "up", name, timeout=CONNECT_TIMEOUT + 15)
            if up.returncode != 0:
                self.nm("connection", "delete", name)
                raise RuntimeError(f"No se pudo conectar a \"{ssid}\". Revisa la clave e inténtalo de nuevo.")
            self.last_connected = ssid
            self.needs_setup = False
            self._offline_since = None
            log.info("connected to %r", ssid)
        except (RuntimeError, subprocess.SubprocessError) as e:
            self.last_error = str(e)
            log.warning("wifi connect failed: %s", e)
            device = self.wifi_device()
            if device:
                self.start_hotspot(device)
        finally:
            self.connecting = False

    # ---------- periodic check ----------

    def _busy_on_screen(self):
        if not self._state_dir:
            return False
        try:
            return time.time() - float((self._state_dir / "wifi-busy").read_text()) < BUSY_MAX_AGE
        except (OSError, ValueError):
            return False

    def _share_status(self):
        if not self._state_dir:
            return
        data = {**self.status_cache, "networks": self.networks, "hotspot_error": self.hotspot_error}
        try:
            tmp = self._state_dir / "wifi-status.json.tmp"
            tmp.write_text(json.dumps(data))
            tmp.replace(self._state_dir / "wifi-status.json")
        except OSError:
            pass

    def tick(self):
        """Called every few seconds: open the setup network when the box has
        been offline for a while, close it once a network works."""
        try:
            self._tick()
        finally:
            self._share_status()

    def _tick(self):
        if self.connecting:
            return
        status = self.status()
        self.status_cache = status
        if not status["has_wifi"]:
            self.needs_setup = False
            return
        now = self._clock()
        if status["connected"]:
            self._offline_since = None
            self.needs_setup = False
            if status["hotspot"]:
                self.stop_hotspot()
            if not self._was_online:
                self.just_connected = True
            self._was_online = True
            return
        self._was_online = False
        if self._offline_since is None:
            self._offline_since = now
        saved = self.saved_home_networks()

        if status["hotspot"]:
            if self._hotspot_since is None:
                self._hotspot_since = now
            # never configured: the screen shows how to set it up. Already
            # configured (router off, new router): the TV keeps playing
            self.needs_setup = not saved
            if saved and now - self._hotspot_since >= RETRY_HOME_EVERY:
                log.info("closing the setup network to look for the home network again")
                self.stop_hotspot()
                self._hotspot_since = None
                self._offline_since = now
            return

        self._hotspot_since = None
        grace = OFFLINE_GRACE if saved else FIRST_SETUP_GRACE
        # never configured and still offline: show the setup screen even if the
        # setup network fails to open, so the TV never sits on a black screen
        self.needs_setup = not saved and now - self._offline_since >= grace
        if self._busy_on_screen() or now < self._hotspot_retry_at:
            return
        if now - self._offline_since >= grace:
            self.start_hotspot(self.wifi_device())
            self.status_cache = self.status()
            if self.status_cache.get("hotspot"):
                self._hotspot_since = now
