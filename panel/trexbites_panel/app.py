"""T-Rex Bites panel: the web page parents open at http://trexbites.local."""

import os
import re
import shutil
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import channels
from .fs42 import FS42Client, FS42Error
from .state import PanelState

FS42_DIR = Path(os.environ.get("TREXBITES_FS42_DIR", "/opt/trexbites/fieldstation42"))
FS42_URL = os.environ.get("TREXBITES_FS42_URL", "http://127.0.0.1:4242")
STATE_PATH = Path(os.environ.get("TREXBITES_STATE", "/var/lib/trexbites/panel.json"))
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

SESSION_COOKIE = "trexbites_session"
SESSION_MAX_AGE = 365 * 24 * 60 * 60
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 5 * 60
# keep this much disk free so the system never fills up completely
DISK_RESERVE_BYTES = 1024 ** 3

VIDEO_EXTENSIONS = {
    ".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".mpg", ".mpeg", ".ts", ".wmv", ".flv",
}

app = FastAPI(title="T-Rex Bites", docs_url=None, redoc_url=None, openapi_url=None)
app.state.panel = PanelState(STATE_PATH)
app.state.fs42 = FS42Client(FS42_URL, FS42_DIR)
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
                # placeholder clips that ship with T-Rex Bites start with "_"
                "placeholder": path.name.startswith("_"),
            })
    return videos


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
    return {"online": online, "player": player, "rebuilds": client.rebuilds}


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
        result.append({**{k: channel[k] for k in ("name", "long_name", "number", "type")},
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
    fs42_client(request).schedule_rebuild(ch["name"])
    return {"ok": True}
