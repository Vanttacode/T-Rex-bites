"""Back up and restore the T-Rex Bites setup: channels, schedules, commercials
settings, logos, bedtime and TV options. Videos are not included (too big):
they stay on the TV's disk, or are copied with a USB stick.
"""

import io
import json
import time
import zipfile
from pathlib import Path

from . import channels

FORMAT = "trexbites-backup"
VERSION = 1
MAX_BACKUP_BYTES = 30 * 1024 * 1024
MAX_LOGO_BYTES = 5 * 1024 * 1024
# panel settings worth carrying over (the PIN stays as it is on each TV)
SETTINGS_KEYS = ("bedtime", "tv")


class BackupError(ValueError):
    pass


def build(confs_dir, fs42_dir, state, version, osd_path=None):
    """The backup as zip bytes."""
    buf = io.BytesIO()
    stations = channels.load_stations(confs_dir)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {"format": FORMAT, "version": VERSION, "trexbites": version,
                    "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "channels": []}
        for conf in stations:
            name = conf["network_name"]
            manifest["channels"].append(name)
            zf.writestr(f"channels/{name}.json", json.dumps({"station_conf": conf}, indent=2, ensure_ascii=False))
            if conf.get("content_dir"):
                logo = channels.logo_file(conf, fs42_dir)
                if logo:
                    zf.write(logo, f"logos/{name}/{logo.name}")
        settings = {k: state.get(k) for k in SETTINGS_KEYS if state.get(k) is not None}
        zf.writestr("settings.json", json.dumps(settings, indent=2, ensure_ascii=False))
        if osd_path and Path(osd_path).is_file():
            zf.write(osd_path, "osd.json")
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
    return buf.getvalue()


def read(data):
    """Check a backup file and return {"manifest", "stations": [conf], "logos": {name: (file, bytes)},
    "settings": {}, "osd": bytes|None}."""
    if len(data) > MAX_BACKUP_BYTES:
        raise BackupError("El archivo es demasiado grande para ser un respaldo.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        manifest = json.loads(zf.read("manifest.json"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise BackupError("Ese archivo no es un respaldo de T-Rex Bites.")
    if manifest.get("format") != FORMAT or not isinstance(manifest.get("version"), int):
        raise BackupError("Ese archivo no es un respaldo de T-Rex Bites.")
    if manifest["version"] > VERSION:
        raise BackupError("Ese respaldo es de una versión más nueva: actualiza T-Rex Bites primero.")
    stations, logos = [], {}
    for info in zf.infolist():
        parts = Path(info.filename).parts
        if info.is_dir() or ".." in parts:
            continue
        if len(parts) == 2 and parts[0] == "channels" and parts[1].endswith(".json"):
            try:
                conf = json.loads(zf.read(info)).get("station_conf")
            except (ValueError, AttributeError):
                raise BackupError(f"El canal {parts[1]} del respaldo está dañado.")
            if not isinstance(conf, dict) or not isinstance(conf.get("network_name"), str):
                raise BackupError(f"El canal {parts[1]} del respaldo está dañado.")
            _check_station(conf)
            stations.append(conf)
        elif len(parts) == 3 and parts[0] == "logos":
            if Path(parts[2]).suffix.lower() in channels.LOGO_EXTENSIONS and info.file_size <= MAX_LOGO_BYTES:
                logos[parts[1]] = (parts[2], zf.read(info))
    try:
        settings = json.loads(zf.read("settings.json"))
    except (KeyError, ValueError):
        settings = {}
    settings = {k: v for k, v in settings.items() if k in SETTINGS_KEYS} if isinstance(settings, dict) else {}
    try:
        osd = zf.read("osd.json")
        json.loads(osd)
    except (KeyError, ValueError):
        osd = None
    numbers = [s.get("channel_number") for s in stations]
    if len(numbers) != len(set(numbers)):
        raise BackupError("El respaldo tiene dos canales con el mismo número.")
    return {"manifest": manifest, "stations": stations, "logos": logos, "settings": settings, "osd": osd}


def _check_station(conf):
    """A restored config must not point FieldStation42 outside its own folders."""
    name = conf["network_name"]
    if not name or "/" in name or name.startswith(".") or len(name) > 60:
        raise BackupError("Un canal del respaldo tiene un nombre inválido.")
    content = conf.get("content_dir")
    if content is not None and (not isinstance(content, str) or Path(content).is_absolute()
                                or ".." in Path(content).parts):
        raise BackupError(f"El canal {name} del respaldo usa una carpeta inválida.")
    if conf.get("network_type") not in ("standard", "loop", "guide"):
        raise BackupError(f"El canal {name} del respaldo es de un tipo que T-Rex Bites no maneja.")
