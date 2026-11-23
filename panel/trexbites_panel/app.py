"""T-Rex Bites panel: the web page parents open at http://trexbites.local."""

import asyncio
import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from urllib.parse import quote
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import backup, bedtime, channels, library, media, migrate, updates, usb, watch
from .fs42 import FS42Client, FS42Error
from .history import History
from .state import PanelState
from .wifi import HOTSPOT_IP, WifiManager, validate as validate_wifi

log = logging.getLogger("trexbites.panel")

FS42_DIR = Path(os.environ.get("TREXBITES_FS42_DIR", "/opt/trexbites/fieldstation42"))
FS42_URL = os.environ.get("TREXBITES_FS42_URL", "http://127.0.0.1:4242")
STATE_PATH = Path(os.environ.get("TREXBITES_STATE", "/var/lib/trexbites/panel.json"))
HISTORY_PATH = Path(os.environ.get("TREXBITES_HISTORY", "/var/lib/trexbites/history.db"))
PLACEHOLDER = Path(os.environ.get("TREXBITES_PLACEHOLDER", "/opt/trexbites/media/_bienvenida_trexbites.mp4"))
IDENT = Path(os.environ.get("TREXBITES_IDENT", "/opt/trexbites/media/_ident_trexbites.mp4"))
VERSION_FILE = Path(os.environ.get("TREXBITES_VERSION_FILE", "/opt/trexbites/VERSION"))
UPDATE_STATE = Path(os.environ.get("TREXBITES_UPDATE_STATE", "/var/lib/trexbites/update.json"))
TREX_CONF = Path(os.environ.get("TREXBITES_CONF", "/opt/trexbites/trexbites.conf"))
# "systemd" starts trexbites-update.service; "none" disables it (development, tests)
UPDATE_BACKEND = os.environ.get("TREXBITES_UPDATE", "systemd")
MAX_LOGO_BYTES = 5 * 1024 * 1024
# "systemd" switches the screen for bedtime; "none" only computes it (development, tests)
POWER_BACKEND = os.environ.get("TREXBITES_POWER", "systemd")
# "nmcli" manages WiFi through NetworkManager; "none" disables it (development, tests)
WIFI_BACKEND = os.environ.get("TREXBITES_WIFI", "nmcli")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
STATE_DIR = STATE_PATH.parent
MEDIA_CACHE = Path(os.environ.get("TREXBITES_MEDIA_CACHE", str(STATE_DIR / "media.json")))
THUMBS_DIR = Path(os.environ.get("TREXBITES_THUMBS", str(STATE_DIR / "thumbs")))
# fs42.service reads TREX_TRANSITION (channel change effect) from here
PLAYER_ENV = Path(os.environ.get("TREXBITES_PLAYER_ENV", str(STATE_DIR / "player.env")))
LOGO_IMAGE = Path(os.environ.get("TREXBITES_LOGO_IMAGE", "/opt/trexbites/media/logo_trexbites.png"))
OSD_CONF = Path(os.environ.get("TREXBITES_OSD", str(FS42_DIR / "osd" / "osd.json")))
MEDIA_DIR = Path(os.environ.get("TREXBITES_MEDIA_DIR", "/srv/trexbites"))
# "udisks" mounts USB sticks; "none" disables it (development, tests)
USB_BACKEND = os.environ.get("TREXBITES_USB", "udisks")
# "ffmpeg" converts heavy videos in the background; "none" disables it (tests)
CONVERT_BACKEND = os.environ.get("TREXBITES_CONVERT", "ffmpeg")
GUIDE_MUSIC_DIR = "_guia_musica"
AUDIO_EXTENSIONS = {".mp3"}
TRANSITIONS = {"long": "Estática (como tele antigua)", "short": "Corto (un poco de interferencia)",
               "none": "Ninguno (cambio directo)"}
DEFAULT_TV = {"transition": "long", "convert": True, "normalize": True}

PLACEHOLDER_NAME = "_bienvenida_trexbites.mp4"
LOOP_SECONDS = 20

SESSION_COOKIE = "trexbites_session"
SESSION_MAX_AGE = 365 * 24 * 60 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 5 * 60
# keep this much disk free so the system never fills up completely
DISK_RESERVE_BYTES = 1024 ** 3

VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".mpg", ".mpeg", ".ts", ".wmv", ".flv",
}

def bedtime_settings(state):
    return {**bedtime.DEFAULT_SETTINGS, **(state.get("bedtime") or {})}


async def apply_power(app_, now=None):
    """Work out whether the TV should be on or showing "¡A dormir!", and make it so."""
    now = now or dt.datetime.now()
    state = app_.state.panel
    override = state.get("power_override")
    if override and override.get("until", 0) <= now.timestamp():
        state.set("power_override", None)
        override = None
    power_state, reason, until = bedtime.desired_state(now, bedtime_settings(state), override)
    if app_.state.wifi.needs_setup:
        # first start without any network: the screen explains how to set up WiFi
        power_state, reason, until = "setup", "wifi", None
    app_.state.power = {"state": power_state, "reason": reason,
                        "until": until.isoformat(timespec="minutes") if until else None}
    if POWER_BACKEND == "systemd":
        await asyncio.to_thread(app_.state.tv_power.apply, power_state)
    return app_.state.power


async def announce_address(app_):
    """Once online, show on the TV where the panel is, in case trexbites.local fails."""
    wifi = app_.state.wifi
    ip = wifi.status_cache.get("ip")
    message = "Entra desde tu teléfono a http://trexbites.local"
    if ip:
        message += f"  ·  o a http://{ip}"
    try:
        await app_.state.fs42.request("POST", "/player/ticker", body={
            "message": message, "header": "T-Rex Bites conectado", "iterations": 3})
        wifi.just_connected = False
    except FS42Error:
        pass  # the player may still be starting: try again on the next pass


async def tv_loop(app_):
    last_sample = 0.0
    while True:
        try:
            if WIFI_BACKEND == "nmcli":
                await asyncio.to_thread(app_.state.wifi.tick)
                if app_.state.wifi.just_connected:
                    await announce_address(app_)
            power = await apply_power(app_)
            if power["state"] == "on" and time.monotonic() - last_sample >= 60:
                last_sample = time.monotonic()
                try:
                    status = await app_.state.fs42.status()
                    await asyncio.to_thread(app_.state.history.record_minute, dt.datetime.now(), status)
                except FS42Error:
                    pass
        except Exception:  # the loop must survive anything; the next pass retries
            log.exception("tv loop pass failed")
        await asyncio.sleep(LOOP_SECONDS)


@asynccontextmanager
async def lifespan(app_):
    app_.state.loop = asyncio.get_running_loop()
    task = asyncio.create_task(tv_loop(app_))
    yield
    task.cancel()


def tv_settings(state):
    return {**DEFAULT_TV, **(state.get("tv") or {})}


def from_thread(fn, *args):
    """Run fn on the event loop (rebuilds are scheduled there) from a worker thread."""
    loop = getattr(app.state, "loop", None)
    if loop and loop.is_running():
        loop.call_soon_threadsafe(fn, *args)


def _converted(path):
    """A video was converted (maybe renamed to .mp4): channels must rescan."""
    from_thread(rebuild_all, app.state.fs42)


def rebuild_all(client, restart=False):
    for conf in channels.load_stations(FS42_DIR / "confs"):
        if channels.is_channel(conf):
            client.schedule_rebuild(conf["network_name"], restart=restart)


app = FastAPI(title="T-Rex Bites", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.state.panel = PanelState(STATE_PATH)
app.state.fs42 = FS42Client(FS42_URL, FS42_DIR)
app.state.history = History(HISTORY_PATH)
app.state.tv_power = bedtime.TVPower()
app.state.wifi = WifiManager(state_dir=STATE_PATH.parent)
app.state.updates = updates.UpdateChecker()
app.state.power = {"state": "on", "reason": None, "until": None}
app.state.media = media.MediaInfo(MEDIA_CACHE)
app.state.thumbs = media.Thumbnails(THUMBS_DIR)
app.state.converter = media.Converter(app.state.media, lambda: tv_settings(app.state.panel), _converted)
app.state.usb_job = usb.ImportJob()
if POWER_BACKEND == "systemd":
    # restart the TV's own services directly: the player and the on-screen logo
    # only read channel names and logos when they start
    app.state.fs42.restart_fn = app.state.tv_power.restart_tv
_login_failures = defaultdict(deque)


# ---------- helpers ----------

def panel_state(request: Request) -> PanelState:
    return request.app.state.panel


def fs42_client(request: Request) -> FS42Client:
    return request.app.state.fs42


def require_session(request: Request):
    if not panel_state(request).valid_session(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(status_code=401, detail="Ingresa el PIN.")


def set_session_cookie(response, state: PanelState):
    response.set_cookie(
        SESSION_COOKIE, state.session_token(), max_age=SESSION_MAX_AGE,
        httponly=True, samesite="strict", path="/",
    )


def _client_ip(request: Request):
    return request.client.host if request.client else "?"


def _login_blocked(ip):
    failures = _login_failures[ip]
    now = time.monotonic()
    while failures and now - failures[0] > LOGIN_WINDOW_SECONDS:
        failures.popleft()
    return len(failures) >= LOGIN_MAX_FAILURES


def all_channels():
    return channels.channel_summaries(FS42_DIR / "confs", FS42_DIR)


def library_tree():
    return library.load(FS42_DIR)


def library_tags():
    return [tag for tag, _ in library.content_tags(library_tree())]


def find_folder(channel_name, tag):
    """(channel summary or None, folder). Without a channel, tag is a library
    category or program; with one, it is one of that channel's own folders."""
    tag = tag or None
    if not channel_name:
        if tag and tag in library_tags():
            return None, library.folder(FS42_DIR, tag)
        raise HTTPException(status_code=404, detail="Esa categoría o programa no existe.")
    for channel in all_channels():
        if channel["name"] != channel_name:
            continue
        for folder in channel["folders"]:
            if folder["tag"] == tag:
                return channel, Path(folder["path"])
    raise HTTPException(status_code=404, detail="Ese canal o carpeta no existe.")


def rebuild_for(client, channel, tag):
    """Rescan what a change in this folder affects."""
    if channel:
        client.schedule_rebuild(channel["name"])
    else:
        for name in channels.channels_using(FS42_DIR / "confs", tag):
            client.schedule_rebuild(name)


_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def safe_filename(name):
    name = _UNSAFE_CHARS.sub("_", Path(name or "").name).strip().strip(".")
    if not name:
        raise HTTPException(status_code=400, detail="El archivo no tiene nombre.")
    if Path(name).suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Ese archivo no parece un video.")
    if len(name.encode()) > 200:
        stem, suffix = Path(name).stem, Path(name).suffix
        name = stem.encode()[: 200 - len(suffix.encode())].decode(errors="ignore") + suffix
    return name


def unique_path(folder, name):
    target = folder / name
    stem, suffix = target.stem, target.suffix
    n = 2
    while target.exists():
        target = folder / f"{stem} ({n}){suffix}"
        n += 1
    return target


def _when_of(parts):
    """Spanish description of hint folders, e.g. ("prime", "saturday") -> "Noche · Sábado"."""
    names = {**channels.WHEN_PARTS, **channels.WHEN_DAYS, **channels.WHEN_MONTHS}
    return " · ".join(names.get(p, p).split(" (")[0] for p in parts)


def _is_hint(name):
    return name in channels.WHEN_PARTS or name in channels.WHEN_DAYS or name in channels.WHEN_MONTHS


def _video_files(folder, extensions=None):
    """(relative name, Path) for the videos in a folder and in its "when" hint
    subfolders (program subfolders are listed on their own)."""
    extensions = extensions or VIDEO_EXTENSIONS
    if not folder.is_dir():
        return []
    found = []

    def walk(directory, parts):
        for path in sorted(directory.iterdir(), key=lambda p: p.name.lower()):
            if path.is_dir() and _is_hint(path.name) and len(parts) < 3:
                walk(path, parts + (path.name,))
            elif path.is_file() and path.suffix.lower() in extensions:
                found.append(("/".join(parts + (path.name,)), path, parts))

    walk(folder, ())
    return found


def list_videos(folder, info=None, extensions=None):
    videos = []
    for rel, path, parts in _video_files(folder, extensions):
        st = path.stat()
        probe = info.cached(path) if info else None
        videos.append({
            "name": rel,
            "file": path.name,
            "size": st.st_size,
            "modified": int(st.st_mtime),
            "when": _when_of(parts) if parts else None,
            "duration": probe.get("duration") if probe else None,
            # the sample clips T-Rex Bites puts in empty folders
            "placeholder": path.name in SAMPLE_NAMES,
        })
    return videos


def has_videos(folder):
    """True if the folder, or any folder inside it, holds a video."""
    if not folder.is_dir():
        return False
    return any(p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS for p in folder.rglob("*"))


SAMPLE_FOR = {channels.COMMERCIAL_TAG: "ident", channels.BUMPS_TAG: "ident", channels.FIXED_TAG: None}


def fill_if_empty(folder, tag=None):
    """FieldStation42 needs at least one video per category: empty folders get
    a sample clip (the short "Ya volvemos" ident for commercials and cortinillas)."""
    folder.mkdir(parents=True, exist_ok=True)
    kind = SAMPLE_FOR.get(tag, "ident" if (tag or "").startswith(channels.PAUTA_PREFIX) else "placeholder")
    if tag is None and folder.name == channels.COMMERCIAL_DIR:
        kind = "ident"
    if kind is None or has_videos(folder):
        return
    if kind == "ident" and IDENT.is_file():
        shutil.copyfile(IDENT, folder / IDENT_NAME)
    elif kind == "placeholder" and PLACEHOLDER.is_file():
        shutil.copyfile(PLACEHOLDER, folder / PLACEHOLDER_NAME)


def remove_placeholder(folder):
    for name in SAMPLE_NAMES:
        (folder / name).unlink(missing_ok=True)


IDENT_NAME = "_ident_trexbites.mp4"
SAMPLE_NAMES = {PLACEHOLDER_NAME, IDENT_NAME}


def ensure_folders(conf):
    """A channel's own folders, with the sample clips FieldStation42 needs."""
    for tag, folder in channels.station_folders(conf, FS42_DIR):
        fill_if_empty(folder, tag)
    bumps = channels.bump_folder(conf, FS42_DIR)
    if bumps:
        fill_if_empty(bumps, channels.BUMPS_TAG)
    channels.logo_folder(conf, FS42_DIR).mkdir(parents=True, exist_ok=True)


def ensure_library():
    for tag in library_tags():
        fill_if_empty(library.folder(FS42_DIR, tag), tag)


def media_roots():
    """Folders whose videos may be sent to a browser (watching on another screen)."""
    return [FS42_DIR / "catalog", FS42_DIR / "runtime", MEDIA_DIR, LOGO_IMAGE.parent, PLACEHOLDER.parent]


def media_root():
    root = FS42_DIR / "catalog"
    return root if root.exists() else FS42_DIR


# ---------- pages ----------

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/programacion", include_in_schema=False)
async def schedule_editor():
    """The timeline editor, made for a computer screen."""
    return FileResponse(STATIC_DIR / "programacion.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(StarletteHTTPException)
async def not_found_to_panel(request: Request, exc: StarletteHTTPException):
    """Unknown pages open the panel. While the setup network is on, phones check
    pages like connectivitycheck.gstatic.com/generate_204 to detect a "captive
    portal": answering with the panel makes the setup page open by itself."""
    if exc.status_code == 404 and request.method == "GET" and not request.url.path.startswith("/api/"):
        if request.app.state.wifi.status_cache.get("hotspot"):
            return RedirectResponse(f"http://{HOTSPOT_IP}/", status_code=302)
        return RedirectResponse("/", status_code=302)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


# ---------- session ----------

class PinBody(BaseModel):
    pin: str


class ChangePinBody(BaseModel):
    current_pin: str
    new_pin: str


@app.get("/api/session")
async def session_info(request: Request):
    state = panel_state(request)
    return {
        "logged_in": state.valid_session(request.cookies.get(SESSION_COOKIE)),
        "pin_is_default": state.pin_is_default,
    }


@app.post("/api/login")
async def login(body: PinBody, request: Request):
    ip = _client_ip(request)
    if _login_blocked(ip):
        raise HTTPException(status_code=429, detail="Demasiados intentos. Espera 5 minutos.")
    state = panel_state(request)
    if not state.check_pin(body.pin):
        _login_failures[ip].append(time.monotonic())
        raise HTTPException(status_code=401, detail="PIN incorrecto.")
    _login_failures.pop(ip, None)
    response = JSONResponse({"ok": True, "pin_is_default": state.pin_is_default})
    set_session_cookie(response, state)
    return response


@app.post("/api/logout")
async def logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@app.post("/api/pin", dependencies=[Depends(require_session)])
async def change_pin(body: ChangePinBody, request: Request):
    state = panel_state(request)
    if not state.check_pin(body.current_pin):
        raise HTTPException(status_code=401, detail="El PIN actual no es correcto.")
    try:
        state.set_pin(body.new_pin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    response = JSONResponse({"ok": True, "pin_is_default": state.pin_is_default})
    set_session_cookie(response, state)
    return response


# ---------- remote control ----------

@app.post("/api/remote/{action}", dependencies=[Depends(require_session)])
async def remote(action: str, request: Request, channel: int | None = None):
    try:
        await fs42_client(request).remote(action, channel)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FS42Error as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True}


@app.get("/api/status", dependencies=[Depends(require_session)])
async def status(request: Request):
    client = fs42_client(request)
    try:
        player = await client.status()
        online = "error" not in player
    except FS42Error:
        player, online = {}, False
    return {"online": online, "player": player, "rebuilds": client.rebuilds,
            "power": request.app.state.power}


# ---------- channels and library ----------

@app.get("/api/channels", dependencies=[Depends(require_session)])
async def get_channels(request: Request):
    info = request.app.state.media
    result = []
    for channel in all_channels():
        folders = [{"tag": f["tag"], "label": f["label"], "videos": list_videos(Path(f["path"]), info)}
                   for f in channel["folders"]]
        result.append({**{k: v for k, v in channel.items() if k != "folders"}, "folders": folders})
    tree = library_tree()
    lib_folders = [{"tag": tag, "label": label,
                    "videos": list_videos(library.folder(FS42_DIR, tag), info)}
                   for tag, label in library.content_tags(tree)]
    rebuilds = request.app.state.fs42.rebuilds
    problems = {name: r["detail"][-300:] for name, r in rebuilds.items()
                if r.get("status") == "error" and not name.startswith("_")}
    return {"channels": result,
            "library": {"categories": tree,
                        "content": [{"tag": t, "label": l} for t, l in library.content_tags(tree)],
                        "folders": lib_folders},
            "problems": problems,
            "when": {"parts": channels.WHEN_PARTS, "days": channels.WHEN_DAYS, "months": channels.WHEN_MONTHS},
            "converting": request.app.state.converter.status()}


@app.get("/api/disk", dependencies=[Depends(require_session)])
async def disk():
    usage = shutil.disk_usage(media_root())
    return {"total": usage.total, "used": usage.used, "free": usage.free}


@app.post("/api/upload", dependencies=[Depends(require_session)])
async def upload(
    request: Request,
    channel: str = Form(""),
    tag: str = Form(""),
    when_part: str = Form(""),
    when_day: str = Form(""),
    when_month: str = Form(""),
    file: UploadFile = File(...),
):
    ch, folder = find_folder(channel or None, tag)
    name = safe_filename(file.filename)
    base_folder = folder
    folder = folder / when_subfolder(when_part, when_day, when_month)
    folder.mkdir(parents=True, exist_ok=True)

    size = file.size or 0
    if size and shutil.disk_usage(folder).free - size < DISK_RESERVE_BYTES:
        raise HTTPException(status_code=507, detail="No queda espacio en el disco de la tele.")

    target = unique_path(folder, name)
    partial = target.with_name(target.name + ".subiendo")
    try:
        with open(partial, "wb") as out:
            shutil.copyfileobj(file.file, out, length=4 * 1024 * 1024)
        os.replace(partial, target)
    except OSError:
        partial.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="No se pudo guardar el video.")
    finally:
        await file.close()

    # the first real video replaces the sample clip
    if target.name != PLACEHOLDER_NAME:
        after_new_video(base_folder)
    queue_conversion(request.app, target)
    rebuild_for(fs42_client(request), ch, tag)
    return {"ok": True, "name": target.name}


def when_subfolder(part="", day="", month=""):
    """Hint folders for "when may this play": morning/saturday/December."""
    parts = []
    for value, allowed in ((part, channels.WHEN_PARTS), (day, channels.WHEN_DAYS), (month, channels.WHEN_MONTHS)):
        if value:
            if value not in allowed:
                raise HTTPException(status_code=400, detail="Momento inválido.")
            parts.append(value)
    return Path(*parts) if parts else Path()


def after_new_video(folder):
    """A real video arrived in folder: the sample clips there (and in the
    category above a program) are no longer needed."""
    remove_placeholder(folder)
    parent = folder.parent
    if parent.name not in ("catalog", channels.PAUTAS_DIR) and (parent / PLACEHOLDER_NAME).exists():
        remove_placeholder(parent)


def queue_conversion(app_, path):
    settings = tv_settings(app_.state.panel)
    if CONVERT_BACKEND == "ffmpeg" and (settings["convert"] or settings["normalize"]):
        app_.state.converter.add(path)


class DeleteBody(BaseModel):
    channel: str | None = None
    tag: str | None = None
    name: str


@app.post("/api/library/delete", dependencies=[Depends(require_session)])
async def delete_video(body: DeleteBody, request: Request):
    ch, folder = find_folder(body.channel, body.tag)
    path = listed_video(folder, body.name)
    path.unlink()
    fill_if_empty(folder, body.tag or None)
    rebuild_for(fs42_client(request), ch, body.tag)
    return {"ok": True}


def listed_video(folder, name, extensions=None):
    """Only a video already listed in this folder (or its "when" subfolders) can be touched."""
    for rel, path, _ in _video_files(folder, extensions):
        if rel == name:
            return path
    raise HTTPException(status_code=404, detail="Ese video no existe.")


# ---------- channel management ----------

class NewChannelBody(BaseModel):
    long_name: str
    number: int
    # "schedule": blocks by hour (timeline editor); "allday": the same content all day
    kind: str = "schedule"
    tags: list[str] = []
    mode: str = "random"


class EditChannelBody(BaseModel):
    long_name: str
    number: int
    # {"enabled": bool, "strategy": "end"|"standard"|"center", "duration": seconds}
    ads: dict | None = None
    # {"show": bool, "permanent": bool}
    logo: dict | None = None
    # commercial pautas: existing as {"tag", "label"}, new ones as plain labels
    pautas: list[str | dict[str, str]] | None = None
    # ask for the channel PIN on the TV before showing this channel
    parental: bool | None = None
    # all-day channels: {"tags": [...], "mode": "random"|"order"}
    allday: dict | None = None


class ScheduleBody(BaseModel):
    # {"monday": [{"start": 7, "end": 10, "kind": "show", "tags": [...], ...}], ...}
    blocks: dict[str, list[dict]]


class DuplicateBody(BaseModel):
    long_name: str
    number: int


def _confs_dir():
    return FS42_DIR / "confs"


def _channel_error(e):
    return HTTPException(status_code=400, detail=str(e))


async def _save_on_tv(coro):
    try:
        await coro
    except FS42Error as e:
        raise HTTPException(status_code=502, detail=f"No se pudo guardar: {e}")


@app.post("/api/channels", dependencies=[Depends(require_session)])
async def create_channel(body: NewChannelBody, request: Request):
    try:
        conf = channels.new_station_conf(channels.load_stations(_confs_dir()), body.long_name, body.number,
                                         body.kind, body.tags, library_tags(), body.mode, FS42_DIR)
    except channels.ChannelError as e:
        raise _channel_error(e)
    # folders first: FieldStation42 skips a channel whose folders don't exist yet
    ensure_folders(conf)
    ensure_library()
    await _save_on_tv(fs42_client(request).create_station(conf))
    fs42_client(request).schedule_rebuild(conf["network_name"], restart=True)
    return {"ok": True, "name": conf["network_name"]}


@app.put("/api/channels/{name}", dependencies=[Depends(require_session)])
async def edit_channel(name: str, body: EditChannelBody, request: Request):
    try:
        old = channels.find_station(_confs_dir(), name)
        conf = channels.update_station_conf(old, channels.load_stations(_confs_dir()), body.long_name,
                                            body.number, body.ads, body.logo, body.pautas, body.parental,
                                            body.allday, library_tags())
    except channels.ChannelError as e:
        raise _channel_error(e)
    ensure_folders(conf)
    await _save_on_tv(fs42_client(request).update_station(name, conf))
    # the player and the on-screen logo only read channel settings when they start
    watched = ("network_name", "channel_number", "network_long_name", "commercial_free", "break_strategy",
               "break_duration", "show_logo", "logo_permanent", "parental_controls")
    restart = any(old.get(key) != conf.get(key) for key in watched)
    # a new name is saved under the old one (FieldStation42 renames it)
    fs42_client(request).schedule_rebuild(conf["network_name"], restart=restart)
    return {"ok": True, "name": conf["network_name"]}


@app.delete("/api/channels/{name}", dependencies=[Depends(require_session)])
async def delete_channel(name: str, request: Request):
    try:
        channels.find_station(_confs_dir(), name)
    except channels.ChannelError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # the library videos stay; so do the channel's own folders (commercials, logo)
    await _save_on_tv(fs42_client(request).delete_station(name))
    fs42_client(request).schedule_restart()
    return {"ok": True}


@app.put("/api/channels/{name}/schedule", dependencies=[Depends(require_session)])
async def save_schedule(name: str, body: ScheduleBody, request: Request):
    try:
        conf = channels.set_blocks(channels.find_station(_confs_dir(), name), body.blocks, library_tags())
    except channels.ChannelError as e:
        raise _channel_error(e)
    ensure_folders(conf)
    await _save_on_tv(fs42_client(request).update_station(name, conf))
    fs42_client(request).schedule_rebuild(name)
    return {"ok": True}


@app.post("/api/channels/{name}/duplicate", dependencies=[Depends(require_session)])
async def duplicate_channel(name: str, body: DuplicateBody, request: Request):
    try:
        source = channels.find_station(_confs_dir(), name)
        conf = channels.duplicate_station_conf(source, channels.load_stations(_confs_dir()),
                                               body.long_name, body.number, FS42_DIR)
    except channels.ChannelError as e:
        raise _channel_error(e)
    # the copy gets the same commercials, cortinillas, fixed videos and logo
    # (hard links: no extra disk space)
    src = library.root(FS42_DIR) / channels.channel_dir(source)
    dest = library.root(FS42_DIR) / channels.channel_dir(conf)
    if src.is_dir() and not dest.exists():
        def link(a, b):
            try:
                os.link(a, b)
            except OSError:
                shutil.copy2(a, b)
        shutil.copytree(src, dest, copy_function=link)
    ensure_folders(conf)
    await _save_on_tv(fs42_client(request).create_station(conf))
    fs42_client(request).schedule_rebuild(conf["network_name"], restart=True)
    return {"ok": True, "name": conf["network_name"]}


# ---------- the library: categories and programs ----------

class LibraryBody(BaseModel):
    # existing as {"tag", "label", "programs": [...]}, new ones as plain labels
    categories: list[str | dict]


@app.put("/api/library", dependencies=[Depends(require_session)])
async def put_library(body: LibraryBody, request: Request):
    old = library_tree()
    try:
        tree = library.clean_tree(body.categories, old)
    except library.LibraryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    removed = library.removed_tags(old, tree)
    for tag in removed:
        users = channels.channels_using(_confs_dir(), tag)
        exact = [c for c in channels.load_stations(_confs_dir())
                 if channels.is_channel(c) and any(u == tag or u.startswith(tag + "/")
                                                    for u in channels.schedule_tags(c))]
        if exact:
            name = exact[0].get("network_long_name") or exact[0]["network_name"]
            raise HTTPException(status_code=400, detail=f"\"{library.label_of(old, tag)}\" lo usa el canal "
                                f"{name}. Quítalo primero de ese canal.")
        del users
        folder = library.folder(FS42_DIR, tag)
        real = [v for v in list_videos(folder) if not v["placeholder"]]
        if real:
            raise HTTPException(status_code=400, detail=f"\"{library.label_of(old, tag)}\" todavía tiene "
                                f"{len(real)} videos. Muévelos o bórralos primero.")
    for tag in sorted(removed, key=lambda t: -t.count("/")):
        folder = library.folder(FS42_DIR, tag)
        remove_placeholder(folder)
        try:
            folder.rmdir()
        except OSError:
            pass
    await asyncio.to_thread(library.save, FS42_DIR, tree)
    ensure_library()
    return {"ok": True, "categories": tree}


class VideoRef(BaseModel):
    channel: str | None = None
    tag: str | None = None
    name: str


class ManyBody(BaseModel):
    items: list[VideoRef]
    to_channel: str | None = None
    to_tag: str | None = None


@app.post("/api/library/move-many", dependencies=[Depends(require_session)])
async def move_many(body: ManyBody, request: Request):
    to_ch, to_folder = find_folder(body.to_channel, body.to_tag)
    client = fs42_client(request)
    moved = 0
    sources = set()
    for item in body.items:
        ch, folder = find_folder(item.channel, item.tag)
        path = listed_video(folder, item.name)
        if path.name in SAMPLE_NAMES or folder == to_folder:
            continue
        to_folder.mkdir(parents=True, exist_ok=True)
        os.replace(path, unique_path(to_folder, path.name))
        sources.add((item.channel or "", item.tag or ""))
        moved += 1
    if moved:
        after_new_video(to_folder)
        for channel_name, tag in sources:
            ch, folder = find_folder(channel_name, tag)
            fill_if_empty(folder, tag or None)
            rebuild_for(client, ch, tag)
        rebuild_for(client, to_ch, body.to_tag)
    return {"ok": True, "moved": moved}


@app.post("/api/library/delete-many", dependencies=[Depends(require_session)])
async def delete_many(body: ManyBody, request: Request):
    client = fs42_client(request)
    deleted = 0
    touched = set()
    for item in body.items:
        ch, folder = find_folder(item.channel, item.tag)
        listed_video(folder, item.name).unlink()
        touched.add((item.channel or "", item.tag or ""))
        deleted += 1
    for channel_name, tag in touched:
        ch, folder = find_folder(channel_name, tag)
        fill_if_empty(folder, tag or None)
        rebuild_for(client, ch, tag)
    return {"ok": True, "deleted": deleted}


# ---------- bedtime and power ----------

class PowerBody(BaseModel):
    mode: str


@app.get("/api/bedtime", dependencies=[Depends(require_session)])
async def get_bedtime(request: Request):
    power = await apply_power(request.app)
    return {"settings": bedtime_settings(panel_state(request)), "power": power}


@app.put("/api/bedtime", dependencies=[Depends(require_session)])
async def put_bedtime(body: dict, request: Request):
    try:
        settings = bedtime.clean_settings(body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    panel_state(request).set("bedtime", settings)
    power = await apply_power(request.app)
    return {"settings": settings, "power": power}


@app.post("/api/power", dependencies=[Depends(require_session)])
async def set_power(body: PowerBody, request: Request):
    state = panel_state(request)
    if body.mode == "auto":
        state.set("power_override", None)
    else:
        try:
            override = bedtime.make_override(body.mode, dt.datetime.now(), bedtime_settings(state))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        state.set("power_override", override)
    return {"power": await apply_power(request.app)}


# ---------- history ----------

@app.get("/api/history", dependencies=[Depends(require_session)])
async def get_history(request: Request, days: int = 7):
    days = max(1, min(days, 31))
    names = {c["name"]: c["long_name"] for c in all_channels()}
    summary = request.app.state.history.summary(dt.date.today(), days)
    for day in summary:
        for program in day["programs"]:
            program["channel_name"] = names.get(program["network"], program["network"])
    return {"days": summary}


# ---------- WiFi ----------

class WifiConnectBody(BaseModel):
    ssid: str
    password: str = ""


def _wifi_info(app_):
    wifi = app_.state.wifi
    return {**wifi.status_cache, "networks": wifi.networks, "connecting": wifi.connecting,
            "last_error": wifi.last_error, "needs_setup": wifi.needs_setup,
            "hotspot_error": wifi.hotspot_error}


@app.get("/api/wifi", dependencies=[Depends(require_session)])
async def get_wifi(request: Request):
    wifi = request.app.state.wifi
    if WIFI_BACKEND == "nmcli" and not wifi.connecting:
        wifi.status_cache = await asyncio.to_thread(wifi.status)
    return _wifi_info(request.app)


@app.post("/api/wifi/scan", dependencies=[Depends(require_session)])
async def scan_wifi(request: Request):
    wifi = request.app.state.wifi
    # while the setup network is on, the WiFi chip can't search: keep the list
    # found just before it opened
    if WIFI_BACKEND == "nmcli" and not wifi.connecting and not wifi.status_cache.get("hotspot"):
        await asyncio.to_thread(wifi.scan)
    return _wifi_info(request.app)


@app.post("/api/wifi/connect", dependencies=[Depends(require_session)])
async def connect_wifi(body: WifiConnectBody, request: Request):
    try:
        ssid, password = validate_wifi(body.ssid, body.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    wifi = request.app.state.wifi
    if wifi.connecting:
        raise HTTPException(status_code=409, detail="Ya se está conectando, espera un momento.")
    if WIFI_BACKEND == "nmcli":
        wifi.connecting = True

        async def later():
            # answer the phone first: joining the home WiFi turns off the setup network
            await asyncio.sleep(3)
            await asyncio.to_thread(wifi.connect, ssid, password)

        asyncio.get_running_loop().create_task(later())
    return {"ok": True, "ssid": ssid}


# ---------------------------------------------------------------------------
# channel logo

def _logo_conf(name):
    try:
        return channels.find_station(_confs_dir(), name)
    except channels.ChannelError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/channels/{name}/logo", dependencies=[Depends(require_session)])
async def get_logo(name: str):
    path = channels.logo_file(_logo_conf(name), FS42_DIR)
    if path is None:
        path = STATIC_DIR / "logo-trexbites.png"  # the T-Rex Bites logo shown by default
    return FileResponse(path, headers={"Cache-Control": "no-cache"})


@app.post("/api/channels/{name}/logo", dependencies=[Depends(require_session)])
async def upload_logo(name: str, request: Request, file: UploadFile = File(...)):
    conf = _logo_conf(name)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in channels.LOGO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="El logo debe ser una imagen PNG, JPG o GIF.")
    data = await file.read(MAX_LOGO_BYTES + 1)
    await file.close()
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(status_code=400, detail="La imagen es muy pesada (máximo 5 MB).")
    folder = channels.logo_folder(conf, FS42_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob("logo.*"):
        old.unlink()
    filename = f"logo{suffix}"
    (folder / filename).write_bytes(data)
    channels.set_logo(conf, None, filename)
    await _save_on_tv(fs42_client(request).update_station(name, conf))
    fs42_client(request).schedule_restart()
    return {"ok": True}


@app.delete("/api/channels/{name}/logo", dependencies=[Depends(require_session)])
async def delete_logo(name: str, request: Request):
    conf = _logo_conf(name)
    for old in channels.logo_folder(conf, FS42_DIR).glob("logo.*"):
        old.unlink()
    channels.set_logo(conf, None, "")
    await _save_on_tv(fs42_client(request).update_station(name, conf))
    fs42_client(request).schedule_restart()
    return {"ok": True}


# ---------------------------------------------------------------------------
# updates

def _current_version():
    try:
        return VERSION_FILE.read_text().strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def _update_state():
    try:
        return json.loads(UPDATE_STATE.read_text())
    except (OSError, ValueError):
        return {}


@app.get("/api/update", dependencies=[Depends(require_session)])
async def get_update(request: Request, check: bool = False):
    checker = request.app.state.updates
    if check:
        await checker.refresh(updates.repo_from_conf(TREX_CONF))
    current = _current_version()
    latest = checker.latest
    return {
        "current": current,
        "latest": latest,
        "available": bool(latest and updates.is_newer(latest["tag"], current)),
        "checked_at": checker.checked_at,
        "error": checker.error,
        "state": _update_state(),
    }


@app.post("/api/update", dependencies=[Depends(require_session)])
async def start_update(request: Request):
    checker = request.app.state.updates
    await checker.refresh(updates.repo_from_conf(TREX_CONF))
    if not (checker.latest and updates.is_newer(checker.latest["tag"], _current_version())):
        raise HTTPException(status_code=409, detail="Ya tienes la última versión.")
    if _update_state().get("status") == "running":
        raise HTTPException(status_code=409, detail="Ya se está actualizando.")
    if UPDATE_BACKEND == "systemd":
        result = await asyncio.to_thread(
            subprocess.run, ["systemctl", "start", "--no-block", "trexbites-update.service"],
            capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail="No se pudo iniciar la actualización.")
    return {"ok": True, "version": checker.latest["tag"]}


# ---------------------------------------------------------------------------
# library: durations, thumbnails, moving videos

@app.post("/api/library/probe", dependencies=[Depends(require_session)])
async def probe_folder(request: Request, body: dict):
    """Durations for a folder's videos (measured the first time, then cached)."""
    _, folder = find_folder(body.get("channel") or None, body.get("tag"))
    info = request.app.state.media

    def run():
        out = {}
        files = _video_files(folder)
        names = [rel for rel, _, _ in files]
        for rel, path, _ in files[:60]:
            probe = info.probe(path)
            out[rel] = probe.get("duration") if probe else None
        # same size and same length in this channel: most likely the same video twice
        return out, names

    durations, _ = await asyncio.to_thread(run)
    return {"durations": durations}


@app.get("/api/library/thumb", dependencies=[Depends(require_session)])
async def thumbnail(request: Request, name: str, channel: str = "", tag: str = ""):
    _, folder = find_folder(channel or None, tag)
    path = listed_video(folder, name)
    info = request.app.state.media.cached(path) or {}
    thumb = await asyncio.to_thread(request.app.state.thumbs.get, path, info.get("duration"))
    if thumb is None:
        return FileResponse(STATIC_DIR / "icon-192.png", headers={"Cache-Control": "max-age=300"})
    return FileResponse(thumb, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/library/move", dependencies=[Depends(require_session)])
async def move_video(body: dict, request: Request):
    """One video (the older single-move call): same as move-many."""
    many = ManyBody(items=[VideoRef(channel=body.get("channel"), tag=body.get("tag"), name=str(body.get("name", "")))],
                    to_channel=body.get("to_channel"), to_tag=body.get("to_tag"))
    return await move_many(many, request)


@app.post("/api/library/convert", dependencies=[Depends(require_session)])
async def convert_folder(request: Request, body: dict):
    """Convert (and level the volume of) every video already in a channel."""
    if CONVERT_BACKEND != "ffmpeg":
        raise HTTPException(status_code=409, detail="La conversión no está disponible en este equipo.")
    count = 0
    folders = [library.folder(FS42_DIR, tag) for tag in library_tags()]
    folders += [Path(f["path"]) for channel in all_channels() for f in channel["folders"]]
    for folder in folders:
        if True:
            for _, path, _ in _video_files(folder):
                if path.name not in SAMPLE_NAMES:
                    request.app.state.converter.add(path)
                    count += 1
    return {"ok": True, "queued": count}


# ---------------------------------------------------------------------------
# TV options: channel change effect, video conversion, volume, channel PIN

class TVSettingsBody(BaseModel):
    transition: str | None = None
    convert: bool | None = None
    normalize: bool | None = None
    # 4 digits asked on the TV for channels marked "con PIN"; "" turns it off
    channel_pin: str | None = None


def _main_config_path():
    return FS42_DIR / "confs" / "main_config.json"


def _read_main_config():
    try:
        return json.loads(_main_config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_player_env(transition):
    PLAYER_ENV.parent.mkdir(parents=True, exist_ok=True)
    PLAYER_ENV.write_text(f"TREX_TRANSITION={transition}\n")


@app.get("/api/tv-settings", dependencies=[Depends(require_session)])
async def get_tv_settings(request: Request):
    settings = tv_settings(panel_state(request))
    pin = str(_read_main_config().get("parental_controls_pin") or "")
    return {**settings, "channel_pin_set": len(pin) == 4, "transitions": TRANSITIONS,
            "converting": request.app.state.converter.status()}


@app.put("/api/tv-settings", dependencies=[Depends(require_session)])
async def put_tv_settings(body: TVSettingsBody, request: Request):
    state = panel_state(request)
    settings = tv_settings(state)
    restart = False
    if body.transition is not None:
        if body.transition not in TRANSITIONS:
            raise HTTPException(status_code=400, detail="Efecto inválido.")
        if body.transition != settings["transition"] or not PLAYER_ENV.exists():
            write_player_env(body.transition)
            restart = True
        settings["transition"] = body.transition
    for key in ("convert", "normalize"):
        value = getattr(body, key)
        if value is not None:
            settings[key] = value
    state.set("tv", settings)
    if body.channel_pin is not None:
        pin = body.channel_pin.strip()
        if pin and not (len(pin) == 4 and pin.isdigit()):
            raise HTTPException(status_code=400, detail="El PIN de canales debe tener 4 números.")
        conf = _read_main_config()
        if not conf.get("api_key"):
            raise HTTPException(status_code=409, detail="No se pudo leer la configuración de la tele.")
        if pin:
            conf["parental_controls_pin"] = pin
        else:
            conf.pop("parental_controls_pin", None)
        # FieldStation42 saves it and restarts the player by itself
        await _save_on_tv(fs42_client(request).request("PUT", "/manage/config", body={"config": conf}, timeout=30))
    elif restart:
        fs42_client(request).schedule_restart()
    return await get_tv_settings(request)


@app.post("/api/remote/digit/{digit}", dependencies=[Depends(require_session)])
async def remote_digit(digit: str, request: Request):
    """Type the channel PIN on the TV from the phone."""
    if digit == "clear":
        path = "/player/parental/clear"
    elif len(digit) == 1 and digit.isdigit():
        path = f"/player/parental/digit/{digit}"
    else:
        raise HTTPException(status_code=400, detail="Número inválido.")
    try:
        await fs42_client(request).request("POST", path)
    except FS42Error as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True}


# ---------------------------------------------------------------------------
# guide channel

class GuideBody(BaseModel):
    enabled: bool
    number: int | None = None
    messages: list[str] | None = None


def _guide_music_folder():
    return FS42_DIR / "catalog" / GUIDE_MUSIC_DIR


def _guide_music():
    folder = _guide_music_folder()
    if not folder.is_dir():
        return []
    return [{"name": p.name, "size": p.stat().st_size}
            for p in sorted(folder.iterdir(), key=lambda p: p.name.lower())
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]


def _build_guide(stations, number, messages):
    images = [LOGO_IMAGE] if LOGO_IMAGE.is_file() else []
    return channels.guide_conf(stations, number, images, _guide_music_folder(), bool(_guide_music()), messages)


@app.get("/api/guide", dependencies=[Depends(require_session)])
async def get_guide():
    guide = channels.find_guide(channels.load_stations(_confs_dir()))
    return {"enabled": guide is not None,
            "number": guide.get("channel_number") if guide else None,
            "messages": guide.get("messages") if guide else None,
            "music": _guide_music()}


@app.put("/api/guide", dependencies=[Depends(require_session)])
async def put_guide(body: GuideBody, request: Request):
    stations = channels.load_stations(_confs_dir())
    guide = channels.find_guide(stations)
    client = fs42_client(request)
    if not body.enabled:
        if guide:
            await _save_on_tv(client.delete_station(guide["network_name"]))
            client.schedule_restart()
        return await get_guide()
    try:
        conf = _build_guide(stations, body.number if body.number is not None else 1,
                            body.messages if body.messages is not None else (guide or {}).get("messages"))
    except channels.ChannelError as e:
        raise _channel_error(e)
    if guide:
        await _save_on_tv(client.update_station(guide["network_name"], conf))
    else:
        await _save_on_tv(client.create_station(conf))
    client.schedule_restart()
    return await get_guide()


async def _refresh_guide(request):
    stations = channels.load_stations(_confs_dir())
    guide = channels.find_guide(stations)
    if guide:
        conf = _build_guide(stations, guide["channel_number"], guide.get("messages"))
        await _save_on_tv(fs42_client(request).update_station(guide["network_name"], conf))
        fs42_client(request).schedule_restart()


@app.post("/api/guide/music", dependencies=[Depends(require_session)])
async def upload_guide_music(request: Request, file: UploadFile = File(...)):
    name = _UNSAFE_CHARS.sub("_", Path(file.filename or "").name).strip().strip(".")
    if not name or Path(name).suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="La música de la guía debe ser un archivo MP3.")
    folder = _guide_music_folder()
    folder.mkdir(parents=True, exist_ok=True)
    target = unique_path(folder, name)
    with open(target, "wb") as out:
        shutil.copyfileobj(file.file, out, length=1024 * 1024)
    await file.close()
    await _refresh_guide(request)
    return {"ok": True, "music": _guide_music()}


@app.post("/api/guide/music/delete", dependencies=[Depends(require_session)])
async def delete_guide_music(body: dict, request: Request):
    name = str(body.get("name", ""))
    if name not in {m["name"] for m in _guide_music()}:
        raise HTTPException(status_code=404, detail="Esa canción no existe.")
    (_guide_music_folder() / name).unlink()
    await _refresh_guide(request)
    return {"ok": True, "music": _guide_music()}


# ---------------------------------------------------------------------------
# backup

@app.get("/api/backup", dependencies=[Depends(require_session)])
async def download_backup(request: Request):
    data = await asyncio.to_thread(backup.build, _confs_dir(), FS42_DIR, panel_state(request),
                                   _current_version(), OSD_CONF)
    stamp = dt.datetime.now().strftime("%Y-%m-%d")
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="trexbites-respaldo-{stamp}.zip"'})


@app.post("/api/backup", dependencies=[Depends(require_session)])
async def restore_backup(request: Request, file: UploadFile = File(...)):
    data = await file.read(backup.MAX_BACKUP_BYTES + 1)
    await file.close()
    try:
        restored = backup.read(data)
    except backup.BackupError as e:
        raise HTTPException(status_code=400, detail=str(e))
    client = fs42_client(request)
    current = {s["network_name"]: s for s in channels.load_stations(_confs_dir())}
    # a channel number taken by a channel that isn't in the backup would clash
    incoming = {s["network_name"] for s in restored["stations"]}
    for name, conf in current.items():
        clash = [s for s in restored["stations"] if s.get("channel_number") == conf.get("channel_number")]
        if name not in incoming and clash:
            await _save_on_tv(client.delete_station(name))
    for conf in restored["stations"]:
        if conf.get("network_type") == "guide":
            stations = channels.load_stations(_confs_dir())
            conf = {**_build_guide([s for s in stations if s["network_name"] != conf["network_name"]],
                                   conf.get("channel_number", 1), conf.get("messages")),
                    "network_name": conf["network_name"]}
        if conf["network_name"] in current:
            await _save_on_tv(client.update_station(conf["network_name"], conf))
        else:
            await _save_on_tv(client.create_station(conf))
        if conf.get("network_type") in ("standard", "loop"):
            logo = restored["logos"].get(conf["network_name"])
            if not channels.is_channel(conf):
                continue  # an older backup: moved into the library below
            if logo and conf.get("default_logo"):
                folder = channels.logo_folder(conf, FS42_DIR)
                folder.mkdir(parents=True, exist_ok=True)
                (folder / conf["default_logo"]).write_bytes(logo[1])
            ensure_folders(conf)
            client.schedule_rebuild(conf["network_name"])
    if restored.get("library"):
        merged = restored["library"] + [c for c in library_tree()
                                        if c["tag"] not in {x["tag"] for x in restored["library"]}]
        await asyncio.to_thread(library.save, FS42_DIR, merged)
    # backups from before the shared library
    await asyncio.to_thread(migrate.migrate, _confs_dir(), FS42_DIR)
    ensure_library()
    for conf in channels.load_stations(_confs_dir()):
        if channels.is_channel(conf):
            ensure_folders(conf)
            client.schedule_rebuild(conf["network_name"])
    state = panel_state(request)
    for key, value in restored["settings"].items():
        state.set(key, value)
    if restored["osd"]:
        try:
            OSD_CONF.parent.mkdir(parents=True, exist_ok=True)
            OSD_CONF.write_bytes(restored["osd"])
        except OSError:
            pass
    write_player_env(tv_settings(state)["transition"])
    client.schedule_restart()
    return {"ok": True, "channels": len(restored["stations"])}


# ---------------------------------------------------------------------------
# import from a USB stick

class USBDevice(BaseModel):
    device: str


class USBImportBody(BaseModel):
    device: str
    files: list[str]
    # no channel: a library category or program
    channel: str | None = None
    tag: str | None = None


def _usb_available():
    if USB_BACKEND != "udisks":
        raise HTTPException(status_code=409, detail="Este equipo no puede leer pendrives.")


def _usb_call(fn, *args):
    try:
        return fn(*args)
    except usb.USBError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/usb", dependencies=[Depends(require_session)])
async def usb_drives(request: Request):
    if USB_BACKEND != "udisks":
        return {"drives": [], "job": request.app.state.usb_job.status()}
    drives = await asyncio.to_thread(_usb_call, usb.list_drives)
    return {"drives": drives, "job": request.app.state.usb_job.status()}


@app.post("/api/usb/open", dependencies=[Depends(require_session)])
async def usb_open(body: USBDevice):
    _usb_available()
    root = await asyncio.to_thread(_usb_call, usb.mount, body.device)
    files = await asyncio.to_thread(usb.list_videos, root, VIDEO_EXTENSIONS)
    return {"mountpoint": root, "files": files}


@app.post("/api/usb/import", dependencies=[Depends(require_session)])
async def usb_import(body: USBImportBody, request: Request):
    _usb_available()
    ch, folder = find_folder(body.channel or None, body.tag)
    root = await asyncio.to_thread(_usb_call, usb.mount, body.device)
    if not body.files:
        raise HTTPException(status_code=400, detail="Elige al menos un video.")
    items = []
    for rel in body.files:
        src = _usb_call(usb.resolve, root, rel)
        if src.suffix.lower() not in VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"{src.name} no parece un video.")
        items.append((src, folder, lambda f, n: unique_path(f, safe_filename(n))))
    total = sum(src.stat().st_size for src, _, _ in items)
    if usb.free_space(folder.parent if not folder.exists() else folder) - total < DISK_RESERVE_BYTES:
        raise HTTPException(status_code=507, detail="No hay espacio suficiente en el disco de la tele.")
    app_ = request.app
    client = fs42_client(request)

    def on_file(dest_folder, target):
        after_new_video(dest_folder)
        queue_conversion(app_, target)

    _usb_call(app_.state.usb_job.start, items, on_file,
              lambda: from_thread(rebuild_for, client, ch, body.tag))
    return {"ok": True, "job": app_.state.usb_job.status()}


@app.get("/api/usb/import", dependencies=[Depends(require_session)])
async def usb_import_status(request: Request):
    return request.app.state.usb_job.status()


@app.post("/api/usb/eject", dependencies=[Depends(require_session)])
async def usb_eject(body: USBDevice, request: Request):
    _usb_available()
    if request.app.state.usb_job.status()["running"]:
        raise HTTPException(status_code=409, detail="Espera a que termine de copiar.")
    await asyncio.to_thread(_usb_call, usb.unmount, body.device)
    return {"ok": True}


# ---------------------------------------------------------------------------
# watch a channel on another screen

@app.get("/ver", include_in_schema=False)
async def watch_page():
    return FileResponse(STATIC_DIR / "ver.html", headers={"Cache-Control": "no-cache"})


def _station_or_404(name):
    try:
        return channels.find_station(_confs_dir(), name)
    except channels.ChannelError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/api/watch/{name}", dependencies=[Depends(require_session)])
async def watch_now(name: str):
    conf = _station_or_404(name)
    playing = await asyncio.to_thread(watch.now_playing, FS42_DIR, conf["network_name"])
    if not playing or playing.get("is_stream"):
        return {"playing": None, "long_name": conf.get("network_long_name") or name}
    path = watch.resolve_media(FS42_DIR, playing["path"], media_roots())
    if path is None:
        return {"playing": None, "long_name": conf.get("network_long_name") or name}
    playing["url"] = f"/api/watch/{name}/media?p={quote(str(path))}"
    playing.pop("path", None)
    return {"playing": playing, "long_name": conf.get("network_long_name") or name}


@app.get("/api/watch/{name}/media", dependencies=[Depends(require_session)])
async def watch_media(name: str, p: str):
    _station_or_404(name)
    path = watch.resolve_media(FS42_DIR, p, media_roots())
    if path is None:
        raise HTTPException(status_code=404, detail="Ese video ya no está.")
    return FileResponse(path, headers={"Cache-Control": "no-store"})
