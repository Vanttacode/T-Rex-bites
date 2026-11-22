"""T-Rex Bites panel: the web page parents open at http://trexbites.local."""

import asyncio
import datetime as dt
import logging
import os
import re
import shutil
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import bedtime, channels
from .fs42 import FS42Client, FS42Error
from .history import History
from .state import PanelState

log = logging.getLogger("trexbites.panel")

FS42_DIR = Path(os.environ.get("TREXBITES_FS42_DIR", "/opt/trexbites/fieldstation42"))
FS42_URL = os.environ.get("TREXBITES_FS42_URL", "http://127.0.0.1:4242")
STATE_PATH = Path(os.environ.get("TREXBITES_STATE", "/var/lib/trexbites/panel.json"))
HISTORY_PATH = Path(os.environ.get("TREXBITES_HISTORY", "/var/lib/trexbites/history.db"))
PLACEHOLDER = Path(os.environ.get("TREXBITES_PLACEHOLDER", "/opt/trexbites/media/_bienvenida_trexbites.mp4"))
IDENT = Path(os.environ.get("TREXBITES_IDENT", "/opt/trexbites/media/_ident_trexbites.mp4"))
# "systemd" switches the screen for bedtime; "none" only computes it (development, tests)
POWER_BACKEND = os.environ.get("TREXBITES_POWER", "systemd")
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

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
    app_.state.power = {"state": power_state, "reason": reason,
                        "until": until.isoformat(timespec="minutes") if until else None}
    if POWER_BACKEND == "systemd":
        await asyncio.to_thread(app_.state.tv_power.apply, power_state)
    return app_.state.power


async def tv_loop(app_):
    last_sample = 0.0
    while True:
        try:
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
    task = asyncio.create_task(tv_loop(app_))
    yield
    task.cancel()


app = FastAPI(title="T-Rex Bites", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.state.panel = PanelState(STATE_PATH)
app.state.fs42 = FS42Client(FS42_URL, FS42_DIR)
app.state.history = History(HISTORY_PATH)
app.state.tv_power = bedtime.TVPower()
app.state.power = {"state": "on", "reason": None, "until": None}
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


def find_folder(channel_name, tag):
    """The folder for a channel and tag, only if the channel config defines it."""
    tag = tag or None
    for channel in all_channels():
        if channel["name"] != channel_name:
            continue
        for folder in channel["folders"]:
            if folder["tag"] == tag:
                return channel, Path(folder["path"])
    raise HTTPException(status_code=404, detail="Ese canal o categoría no existe.")


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


def list_videos(folder):
    if not folder.is_dir():
        return []
    videos = []
    for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            st = path.stat()
            videos.append({
                "name": path.name,
                "size": st.st_size,
                "modified": int(st.st_mtime),
                # the sample clip T-Rex Bites puts in empty folders
                "placeholder": path.name == PLACEHOLDER_NAME,
            })
    return videos


def fill_if_empty(folder):
    """FieldStation42 needs at least one video per category: empty folders get the sample clip."""
    folder.mkdir(parents=True, exist_ok=True)
    if not list_videos(folder) and PLACEHOLDER.is_file():
        shutil.copyfile(PLACEHOLDER, folder / PLACEHOLDER_NAME)


def remove_placeholder(folder):
    (folder / PLACEHOLDER_NAME).unlink(missing_ok=True)


IDENT_NAME = "_ident_trexbites.mp4"


def ensure_folders(conf):
    for _, folder in channels.station_folders(conf, FS42_DIR):
        fill_if_empty(folder)
    bumps = channels.bump_folder(conf, FS42_DIR)
    if bumps:
        bumps.mkdir(parents=True, exist_ok=True)
        if not list_videos(bumps) and IDENT.is_file():
            shutil.copyfile(IDENT, bumps / IDENT_NAME)


def media_root():
    root = FS42_DIR / "catalog"
    return root if root.exists() else FS42_DIR


# ---------- pages ----------

@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
async def get_channels():
    result = []
    for channel in all_channels():
        folders = []
        for folder in channel["folders"]:
            folders.append({
                "tag": folder["tag"],
                "label": folder["label"],
                "videos": list_videos(Path(folder["path"])),
            })
        result.append({**{k: channel[k] for k in ("name", "long_name", "number", "type",
                                                  "categories", "schedule")},
                       "folders": folders})
    return {"channels": result}


@app.get("/api/disk", dependencies=[Depends(require_session)])
async def disk():
    usage = shutil.disk_usage(media_root())
    return {"total": usage.total, "used": usage.used, "free": usage.free}


@app.post("/api/upload", dependencies=[Depends(require_session)])
async def upload(
    request: Request,
    channel: str = Form(...),
    tag: str = Form(""),
    file: UploadFile = File(...),
):
    ch, folder = find_folder(channel, tag)
    name = safe_filename(file.filename)
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
        remove_placeholder(folder)

    fs42_client(request).schedule_rebuild(ch["name"])
    return {"ok": True, "name": target.name}


class DeleteBody(BaseModel):
    channel: str
    tag: str | None = None
    name: str


@app.post("/api/library/delete", dependencies=[Depends(require_session)])
async def delete_video(body: DeleteBody, request: Request):
    ch, folder = find_folder(body.channel, body.tag)
    # only a plain file name that is already listed in this folder can be deleted
    if body.name != Path(body.name).name or body.name not in {v["name"] for v in list_videos(folder)}:
        raise HTTPException(status_code=404, detail="Ese video no existe.")
    (folder / body.name).unlink()
    fill_if_empty(folder)
    fs42_client(request).schedule_rebuild(ch["name"])
    return {"ok": True}


# ---------- channel management ----------

class NewChannelBody(BaseModel):
    long_name: str
    number: int
    type: str = "standard"
    categories: list[str] = []


class EditChannelBody(BaseModel):
    long_name: str
    number: int
    # existing categories as {"tag", "label"}, new ones as plain labels
    categories: list[str | dict[str, str]] | None = None


class ScheduleBody(BaseModel):
    week: dict[str, dict[str, str]]


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
        conf = channels.new_station_conf(channels.load_stations(_confs_dir()), body.long_name,
                                         body.number, body.type, body.categories)
    except channels.ChannelError as e:
        raise _channel_error(e)
    await _save_on_tv(fs42_client(request).create_station(conf))
    ensure_folders(conf)
    fs42_client(request).schedule_rebuild(conf["network_name"], restart=True)
    return {"ok": True, "name": conf["network_name"]}


@app.put("/api/channels/{name}", dependencies=[Depends(require_session)])
async def edit_channel(name: str, body: EditChannelBody, request: Request):
    try:
        old = channels.find_station(_confs_dir(), name)
        conf = channels.update_station_conf(old, channels.load_stations(_confs_dir()), body.long_name,
                                            body.number, body.categories)
    except channels.ChannelError as e:
        raise _channel_error(e)
    await _save_on_tv(fs42_client(request).update_station(name, conf))
    ensure_folders(conf)
    # the player only reads channel names and numbers when it starts
    restart = (old.get("channel_number") != conf["channel_number"]
               or old.get("network_long_name") != conf.get("network_long_name"))
    fs42_client(request).schedule_rebuild(name, restart=restart)
    return {"ok": True}


@app.delete("/api/channels/{name}", dependencies=[Depends(require_session)])
async def delete_channel(name: str, request: Request):
    try:
        channels.find_station(_confs_dir(), name)
    except channels.ChannelError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # the channel's videos stay on disk; a new channel with the same name finds them again
    await _save_on_tv(fs42_client(request).delete_station(name))
    fs42_client(request).schedule_restart()
    return {"ok": True}


@app.put("/api/channels/{name}/schedule", dependencies=[Depends(require_session)])
async def save_schedule(name: str, body: ScheduleBody, request: Request):
    try:
        conf = channels.set_week(channels.find_station(_confs_dir(), name), body.week)
    except channels.ChannelError as e:
        raise _channel_error(e)
    await _save_on_tv(fs42_client(request).update_station(name, conf))
    ensure_folders(conf)
    fs42_client(request).schedule_rebuild(name)
    return {"ok": True}


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
