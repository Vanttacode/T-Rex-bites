"""Read and edit FieldStation42 channel configs.

Every channel plays videos from the shared library (see library.py): all of
them use catalog/biblioteca as content_dir, so a library tag ("dibujos",
"dibujos/bluey") means the same videos on every channel. What belongs to one
channel only (commercials, pautas, cortinillas, fixed videos, logo) lives in
catalog/biblioteca/canales/<channel>/.

Two kinds of channel, both FieldStation42 "standard" networks:
  schedule  blocks by hour and day, made in the timeline editor
  allday    the same content all day, every day, one video after the other

Standard library only: the installer runs this module before the panel's
virtualenv exists.
"""

import argparse
import copy
import json
from pathlib import Path

from . import library  # noqa: E402  (also importable as a plain script, see main)

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SIGNOFF = "signoff"
MAX_NAME_LENGTH = 30
KINDS = ("schedule", "allday")

# folders of one channel, inside library/canales/<channel>/
BUMP_DIR = "bumps"
COMMERCIAL_DIR = "comerciales"
PAUTAS_DIR = "pautas"
FIXED_DIR = "fijos"
LOGO_DIR = "logos"
LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif")
# how the panel names those folders
COMMERCIAL_TAG = "_comerciales"
PAUTA_PREFIX = "_pauta/"
BUMPS_TAG = "_cortinillas"
FIXED_TAG = "_fijos"
MAX_PAUTAS = 12

# when commercial breaks happen (FieldStation42's break_strategy)
BREAK_STRATEGIES = {
    "end": "Al final de cada programa",
    "standard": "Repartidos durante el programa",
    "center": "Una tanda a la mitad del programa",
}
MIN_BREAK, MAX_BREAK = 15, 600

# Folder names FieldStation42 reads as "when this may play" hints. A video in
# comerciales/morning/ only plays in the morning; folders can be nested.
WHEN_PARTS = {
    "morning": "Mañana (6 a 10 h)",
    "daytime": "Día (10 a 18 h)",
    "prime": "Noche (18 a 23 h)",
    "late": "Trasnoche (23 a 2 h)",
    "overnight": "Madrugada (2 a 6 h)",
}
WHEN_DAYS = {
    "monday": "Lunes", "tuesday": "Martes", "wednesday": "Miércoles", "thursday": "Jueves",
    "friday": "Viernes", "saturday": "Sábado", "sunday": "Domingo",
}
WHEN_MONTHS = {
    "January": "Enero", "February": "Febrero", "March": "Marzo", "April": "Abril",
    "May": "Mayo", "June": "Junio", "July": "Julio", "August": "Agosto",
    "September": "Septiembre", "October": "Octubre", "November": "Noviembre", "December": "Diciembre",
}

# runtime files that FieldStation42's installer puts in place
RUNTIME_MEDIA = {
    "sign_off_video": "runtime/signoff.mp4",
    "off_air_video": "runtime/off_air_pattern.mp4",
    "standby_image": "runtime/standby.png",
    "be_right_back_media": "runtime/brb.png",
}
MAX_BLOCK_MINUTES = 600
BLOCK_VIDEO_KEYS = ("start_video", "end_video")


class ChannelError(ValueError):
    """A change the person asked for that can't be made; the message is shown to them."""


slugify = library.slugify


def clean_label(text, what="El nombre"):
    try:
        return library.clean_label(text, what)
    except library.LibraryError as e:
        raise ChannelError(str(e))


def folder_label(tag, pautas=()):
    if tag == COMMERCIAL_TAG:
        return "📺 Comerciales (todo el canal)"
    if tag == BUMPS_TAG:
        return "🎬 Cortinillas (entre programas)"
    if tag == FIXED_TAG:
        return "📌 Videos fijos (inicio o fin de bloque)"
    if tag.startswith(PAUTA_PREFIX):
        name = tag[len(PAUTA_PREFIX):]
        label = next((p["label"] for p in pautas if p["tag"] == name), library.default_label(name))
        return f"📺 Pauta: {label}"
    return tag


# ---------- reading ----------

def _station_files(confs_dir):
    for path in sorted(Path(confs_dir).glob("*.json")):
        if path.name == "main_config.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        conf = data.get("station_conf") if isinstance(data, dict) else None
        if isinstance(conf, dict) and "network_name" in conf:
            yield path, conf


def load_stations(confs_dir):
    """Every station_conf in confs_dir, sorted by channel number."""
    stations = [conf for _, conf in _station_files(confs_dir)]
    stations.sort(key=lambda s: (s.get("channel_number", 0), s["network_name"]))
    return stations


def find_station(confs_dir, network_name):
    for _, conf in _station_files(confs_dir):
        if conf["network_name"] == network_name:
            return copy.deepcopy(conf)
    raise ChannelError("Ese canal no existe.")


def is_channel(conf):
    """A channel T-Rex Bites manages (not the guide or something made in FS42's console)."""
    return conf.get("network_type") == "standard" and conf.get("content_dir") == library.CONTENT_DIR


def kind(conf):
    return "allday" if (conf.get("trexbites") or {}).get("kind") == "allday" else "schedule"


def channel_dir(conf):
    """library-relative folder of one channel ("canales/trextv")."""
    stored = (conf.get("trexbites") or {}).get("folder")
    if isinstance(stored, str) and stored.startswith(library.CHANNELS_DIR + "/") and ".." not in stored:
        return stored
    return f"{library.CHANNELS_DIR}/{slugify(conf['network_name'])}"


def _add_tags(value, tags):
    if isinstance(value, str) and value:
        if value not in tags:
            tags.append(value)
    elif isinstance(value, list):
        for item in value:
            _add_tags(item, tags)


def schedule_tags(conf):
    """Library tags used by a station's weekly schedule."""
    tags = []
    for day in DAYS:
        slots = conf.get(day)
        if not isinstance(slots, dict):
            continue
        for hour in sorted(slots, key=lambda h: int(h) if str(h).isdigit() else 99):
            slot = slots[hour]
            if isinstance(slot, dict):
                _add_tags(slot.get("tags"), tags)
    return tags


def channel_pautas(conf):
    result = []
    for item in (conf.get("trexbites") or {}).get("pautas") or []:
        if isinstance(item, dict) and item.get("tag"):
            result.append({"tag": item["tag"], "label": item.get("label") or library.default_label(item["tag"])})
    return result


def _base(fs42_dir):
    return library.root(fs42_dir)


def station_folders(conf, fs42_dir):
    """(tag, folder) for the folders that belong to this channel only."""
    if not is_channel(conf):
        return []
    own = _base(fs42_dir) / channel_dir(conf)
    folders = []
    if ads_enabled(conf):
        folders.append((COMMERCIAL_TAG, own / COMMERCIAL_DIR))
        for pauta in channel_pautas(conf):
            folders.append((PAUTA_PREFIX + pauta["tag"], own / PAUTAS_DIR / pauta["tag"]))
    folders.append((BUMPS_TAG, own / BUMP_DIR))
    if kind(conf) == "schedule":
        folders.append((FIXED_TAG, own / FIXED_DIR))
    return folders


def ads_enabled(conf):
    return (kind(conf) == "schedule" and not conf.get("commercial_free", False)
            and isinstance(conf.get("commercial_dir"), str) and bool(conf.get("commercial_dir")))


def ads_settings(conf):
    return {
        "enabled": ads_enabled(conf),
        "strategy": conf.get("break_strategy", "end") if conf.get("break_strategy") in BREAK_STRATEGIES else "end",
        "duration": int(conf.get("break_duration", 120) or 120),
    }


def logo_folder(conf, fs42_dir):
    return _base(fs42_dir) / channel_dir(conf) / LOGO_DIR


def logo_file(conf, fs42_dir):
    """The channel's uploaded logo, or None (then the T-Rex Bites logo is used)."""
    name = conf.get("default_logo")
    if not conf.get("logo_dir") or not isinstance(name, str) or not name:
        return None
    path = logo_folder(conf, fs42_dir) / name
    return path if path.is_file() else None


def logo_settings(conf, fs42_dir):
    return {
        "show": bool(conf.get("show_logo", True)),
        "permanent": bool(conf.get("logo_permanent", True)),
        "custom": logo_file(conf, fs42_dir) is not None,
    }


# ---------- schedule blocks ----------
#   {"start": 7, "end": 10, "kind": "show", "tags": ["dibujos", "dibujos/bluey"],
#    "mode": "random"|"order", "breaks": null|"end"|"standard"|"center",
#    "min_minutes": null|int, "max_minutes": null|int,
#    "pauta": null|"juguetes", "start_video": null|"file.mp4", "end_video": null|"file.mp4"}
#   {"start": 20, "end": 21, "kind": "signoff"}
# Hours are whole hours (0-24). In FieldStation42 a block is one slot per hour;
# the hours after the first carry "continued": true so the block can be read back.

def _own_name(conf, path, sub):
    prefix = f"{channel_dir(conf)}/{sub}/"
    if isinstance(path, str) and path.startswith(prefix) and "/" not in path[len(prefix):]:
        return path[len(prefix):]
    return None


def _slot_content(conf, slot):
    tags = slot.get("tags")
    tags = [tags] if isinstance(tags, str) else [t for t in (tags or []) if isinstance(t, str)]

    def minutes(key):
        value = slot.get(key)
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    return {
        "kind": "show",
        "tags": tags,
        "mode": "order" if slot.get("sequence") else "random",
        "breaks": slot.get("break_strategy") if slot.get("break_strategy") in BREAK_STRATEGIES else None,
        "min_minutes": minutes("min_duration"),
        "max_minutes": minutes("max_duration"),
        "pauta": _own_name(conf, slot.get("commercial_dir"), PAUTAS_DIR),
    }


def week_blocks(conf):
    """{day: [block]} read from the station's weekly slots."""
    week = {}
    for day in DAYS:
        slots = conf.get(day) if isinstance(conf.get(day), dict) else {}
        blocks = []
        for hour in range(24):
            slot = slots.get(str(hour))
            if not isinstance(slot, dict):
                continue
            if slot.get("event") == SIGNOFF:
                blocks.append({"start": hour, "end": hour + 1, "kind": SIGNOFF})
                continue
            prev = blocks[-1] if blocks else None
            if "tags" not in slot:
                if slot.get("continued") and prev and prev["kind"] == "show" and prev["end"] == hour:
                    prev["end"] = hour + 1
                continue
            content = _slot_content(conf, slot)
            end_video = _own_name(conf, slot.get("end_bump"), FIXED_DIR)
            if (slot.get("continued") and prev and prev["kind"] == "show" and prev["end"] == hour
                    and all(prev[k] == content[k] for k in content)):
                prev["end"] = hour + 1
                if end_video:
                    prev["end_video"] = end_video
            else:
                blocks.append({"start": hour, "end": hour + 1, **content,
                               "start_video": _own_name(conf, slot.get("start_bump"), FIXED_DIR),
                               "end_video": end_video})
        week[day] = blocks
    return week


def sequence_name(tag):
    """One episode order per category or program, shared by its "in order" blocks."""
    return "orden-" + tag.replace("/", "-")


def _plain_file(name, what):
    if name in (None, ""):
        return None
    if not isinstance(name, str) or name != Path(name).name or name.startswith("."):
        raise ChannelError(f"{what} inválido.")
    return name


def _clean_tags(tags, valid_tags):
    if not isinstance(tags, list) or not tags:
        raise ChannelError("Elige al menos una categoría o programa.")
    if len(set(tags)) != len(tags) or any(t not in valid_tags for t in tags):
        raise ChannelError("Usa una categoría o programa que no existe en la biblioteca.")
    return list(tags)


def _clean_block(block, valid_tags, valid_pautas=()):
    if not isinstance(block, dict):
        raise ChannelError("Bloque inválido.")
    try:
        start, end = int(block.get("start")), int(block.get("end"))
    except (TypeError, ValueError):
        raise ChannelError("Las horas de un bloque deben ser números.")
    if not 0 <= start < end <= 24:
        raise ChannelError("Un bloque debe empezar y terminar entre las 0 y las 24 horas.")
    kind_ = block.get("kind")
    if kind_ == SIGNOFF:
        return {"start": start, "end": start + 1, "kind": SIGNOFF}
    if kind_ != "show":
        raise ChannelError("Tipo de bloque inválido.")
    tags = _clean_tags(block.get("tags"), valid_tags)
    mode = block.get("mode", "random")
    if mode not in ("random", "order"):
        raise ChannelError("Modo de bloque inválido.")
    if mode == "order" and len(tags) != 1:
        raise ChannelError("\"Capítulos en orden\" funciona con una sola categoría o programa.")
    breaks = block.get("breaks")
    if breaks is not None and breaks not in BREAK_STRATEGIES:
        raise ChannelError("Estilo de tanda inválido.")
    limits = {}
    for key in ("min_minutes", "max_minutes"):
        value = block.get(key)
        if value in (None, ""):
            limits[key] = None
            continue
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ChannelError("La duración de los videos debe ser un número de minutos.")
        if not 1 <= value <= MAX_BLOCK_MINUTES:
            raise ChannelError("La duración de los videos debe estar entre 1 y 600 minutos.")
        limits[key] = value
    if limits["min_minutes"] and limits["max_minutes"] and limits["min_minutes"] > limits["max_minutes"]:
        raise ChannelError("La duración mínima no puede ser mayor que la máxima.")
    pauta = block.get("pauta") or None
    if pauta is not None and pauta not in valid_pautas:
        raise ChannelError("Un bloque usa una pauta de comerciales que no existe.")
    videos = {key: _plain_file(block.get(key), "Video fijo") for key in BLOCK_VIDEO_KEYS}
    return {"start": start, "end": end, "kind": "show", "tags": tags, "mode": mode,
            "breaks": breaks, **limits, "pauta": pauta, **videos}


def _block_slot(conf, block):
    tags = block["tags"]
    slot = {"tags": tags[0] if len(tags) == 1 else list(tags)}
    if len(tags) > 1:
        slot["random_tags"] = True
    if block["mode"] == "order":
        slot["sequence"] = sequence_name(tags[0])
    if block["breaks"]:
        slot["break_strategy"] = block["breaks"]
    if block["min_minutes"]:
        slot["min_duration"] = block["min_minutes"]
    if block["max_minutes"]:
        slot["max_duration"] = block["max_minutes"]
    if block.get("pauta"):
        slot["commercial_dir"] = f"{channel_dir(conf)}/{PAUTAS_DIR}/{block['pauta']}"
    return slot


def _write_week(conf, week, valid_tags):
    pautas = {p["tag"] for p in channel_pautas(conf)}
    own = channel_dir(conf)
    for day in DAYS:
        blocks = week.get(day) or []
        if not isinstance(blocks, list):
            raise ChannelError("Programación inválida.")
        cleaned = sorted((_clean_block(b, valid_tags, pautas) for b in blocks), key=lambda b: b["start"])
        for before, after in zip(cleaned, cleaned[1:]):
            if after["start"] < before["end"]:
                raise ChannelError("Hay bloques que se superponen el mismo día.")
        slots = {}
        for block in cleaned:
            if block["kind"] == SIGNOFF:
                slots[str(block["start"])] = {"event": SIGNOFF}
                continue
            slot = _block_slot(conf, block)
            hours = range(block["start"], block["end"])
            for hour in hours:
                this = dict(slot) if hour == block["start"] else {**slot, "continued": True}
                # the fixed video plays once when the block starts, and after the
                # programs of its last hour
                if hour == block["start"] and block["start_video"]:
                    this["start_bump"] = f"{own}/{FIXED_DIR}/{block['start_video']}"
                if hour == hours[-1] and block["end_video"]:
                    this["end_bump"] = f"{own}/{FIXED_DIR}/{block['end_video']}"
                slots[str(hour)] = this
        conf[day] = dict(sorted(slots.items(), key=lambda kv: int(kv[0])))
    used = schedule_tags(conf)
    conf["fallback_tag"] = used[0].split("/")[0] if used else conf.get("fallback_tag")


def set_blocks(conf, week, valid_tags):
    """Replace a schedule channel's weekly schedule with {day: [block]}."""
    if not is_channel(conf):
        raise ChannelError("Este canal no se puede editar aquí.")
    if kind(conf) != "schedule":
        raise ChannelError("Este canal pasa lo mismo todo el día: se cambia en Más → Canales.")
    if not isinstance(week, dict):
        raise ChannelError("Programación inválida.")
    conf = copy.deepcopy(conf)
    _write_week(conf, week, set(valid_tags))
    return conf


# ---------- all-day channels ----------

def allday_settings(conf):
    blocks = week_blocks(conf).get("monday") or []
    show = next((b for b in blocks if b["kind"] == "show"), None)
    if not show:
        return {"tags": [], "mode": "random"}
    return {"tags": show["tags"], "mode": show["mode"]}


def set_allday(conf, settings, valid_tags):
    """settings = {"tags": [...], "mode": "random"|"order"}: one block 0-24 every day."""
    if not isinstance(settings, dict):
        raise ChannelError("Configuración inválida.")
    tags = _clean_tags(settings.get("tags"), set(valid_tags))
    mode = settings.get("mode", "random")
    if mode == "order" and len(tags) != 1:
        raise ChannelError("\"En orden\" funciona con una sola categoría o programa.")
    block = {"start": 0, "end": 24, "kind": "show", "tags": tags, "mode": mode}
    _write_week(conf, {d: [block] for d in DAYS}, set(valid_tags))
    # no clock alignment: one video right after the other
    conf["schedule_increment"] = 0


# ---------- summaries ----------

def channel_summaries(confs_dir, fs42_dir):
    channels = []
    for conf in load_stations(confs_dir):
        if not is_channel(conf):
            continue
        pautas = channel_pautas(conf)
        k = kind(conf)
        channels.append({
            "name": conf["network_name"],
            "long_name": conf.get("network_long_name") or conf["network_name"],
            "number": conf.get("channel_number"),
            "kind": k,
            "allday": allday_settings(conf) if k == "allday" else None,
            "blocks": week_blocks(conf) if k == "schedule" else None,
            "ads": ads_settings(conf) if k == "schedule" else None,
            "pautas": pautas,
            "logo": logo_settings(conf, fs42_dir),
            "parental": bool(conf.get("parental_controls")),
            "tags": schedule_tags(conf),
            "folders": [{"tag": tag, "label": folder_label(tag, pautas), "path": str(path)}
                        for tag, path in station_folders(conf, fs42_dir)],
        })
    return channels


def channels_using(confs_dir, tag):
    """Channels whose schedule plays videos of this library tag."""
    names = []
    for conf in load_stations(confs_dir):
        if not is_channel(conf):
            continue
        for used in schedule_tags(conf):
            # a category plays its programs too; a program is part of its category
            if used == tag or tag.startswith(used + "/") or used.startswith(tag + "/"):
                names.append(conf["network_name"])
                break
    return names


# ---------- editing ----------

def _clean_number(number, stations, own_name=None):
    try:
        number = int(number)
    except (TypeError, ValueError):
        raise ChannelError("El número de canal debe ser un número.")
    if not 1 <= number <= 99:
        raise ChannelError("El número de canal debe estar entre 1 y 99.")
    for other in stations:
        if other["network_name"] != own_name and other.get("channel_number") == number:
            name = other.get("network_long_name") or other["network_name"]
            raise ChannelError(f"El canal {number} ya lo usa \"{name}\".")
    return number


def display_name(long_name, stations, own_name=None):
    """FieldStation42's network_name. The TV shows it on screen when the channel
    changes, so it is the channel's visible name (unique among channels)."""
    base = long_name.replace("/", "-").strip() or "Canal"
    taken = {s["network_name"].lower() for s in stations if s["network_name"] != own_name}
    name, n = base, 2
    while name.lower() in taken or slugify(name) in ("main_config", ""):
        name = f"{base} {n}"
        n += 1
    return name


def unique_channel_folder(name, stations, fs42_dir=None):
    """canales/<slug>, not used by another channel nor already on disk."""
    used = {channel_dir(s) for s in stations if is_channel(s)}
    base = f"{library.CHANNELS_DIR}/{slugify(name) or 'canal'}"
    folder, n = base, 2
    while folder in used or (fs42_dir and (library.root(fs42_dir) / folder).exists()):
        folder = f"{base}{n}"
        n += 1
    return folder


def default_week(first_tag):
    """New schedule channels: one block 7:00-20:00, then sign off."""
    block = {"start": 7, "end": 20, "kind": "show", "tags": [first_tag], "mode": "random"}
    return {d: [block, {"start": 20, "end": 21, "kind": SIGNOFF}] for d in DAYS}


def new_station_conf(stations, long_name, number, kind_, tags, valid_tags, mode="random", fs42_dir=None):
    long_name = clean_label(long_name, "El nombre del canal")
    if kind_ not in KINDS:
        raise ChannelError("Tipo de canal inválido.")
    number = _clean_number(number, stations)
    tags = _clean_tags(tags, set(valid_tags))
    name = display_name(long_name, stations)
    conf = {
        "network_name": name,
        "network_long_name": long_name,
        "channel_number": number,
        "network_type": "standard",
        "content_dir": library.CONTENT_DIR,
        "schedule_increment": 30,
        "commercial_free": True,
        "fallback_tag": tags[0].split("/")[0],
        "break_strategy": "end",
        "break_duration": 120,
        **RUNTIME_MEDIA,
        "trexbites": {"kind": kind_, "folder": unique_channel_folder(name, stations, fs42_dir)},
    }
    conf["bump_dir"] = f"{channel_dir(conf)}/{BUMP_DIR}"
    if kind_ == "allday":
        set_allday(conf, {"tags": tags, "mode": mode}, valid_tags)
    else:
        _write_week(conf, default_week(tags[0]), set(valid_tags))
    return conf


def rewrite_channel_paths(conf, old_dir, new_dir):
    """Point a copied config at its own channel folder."""
    old_prefix, new_prefix = old_dir + "/", new_dir + "/"

    def fix(value):
        return new_prefix + value[len(old_prefix):] if isinstance(value, str) and value.startswith(old_prefix) else value

    for key in ("bump_dir", "commercial_dir", "logo_dir"):
        if key in conf:
            conf[key] = fix(conf[key])
    for day in DAYS:
        for slot in (conf.get(day) or {}).values():
            if isinstance(slot, dict):
                for key in ("commercial_dir", "start_bump", "end_bump", "bump_dir"):
                    if key in slot:
                        slot[key] = fix(slot[key])
    conf.setdefault("trexbites", {})["folder"] = new_dir


def rename(conf, stations):
    """Keep network_name (what the TV shows) equal to the visible name. The
    channel's folder is stored first, so renaming never moves files."""
    if not is_channel(conf):
        return
    conf.setdefault("trexbites", {}).setdefault("folder", channel_dir(conf))
    wanted = display_name(conf.get("network_long_name") or conf["network_name"], stations,
                          own_name=conf["network_name"])
    conf["network_name"] = wanted


def duplicate_station_conf(conf, stations, long_name, number, fs42_dir=None):
    """A copy of a channel: same schedule, commercials settings and logo; it
    plays the same library videos and gets its own channel folder."""
    new = copy.deepcopy(conf)
    new["network_long_name"] = clean_label(long_name, "El nombre del canal")
    new["channel_number"] = _clean_number(number, stations)
    new["network_name"] = display_name(new["network_long_name"], stations)
    rewrite_channel_paths(new, channel_dir(conf), unique_channel_folder(new["network_name"], stations, fs42_dir))
    new.pop("schedule_path", None)
    new.pop("catalog_path", None)
    return new


def bump_folder(conf, fs42_dir):
    if not is_channel(conf):
        return None
    return _base(fs42_dir) / channel_dir(conf) / BUMP_DIR


def set_ads(conf, ads):
    """ads = {"enabled": bool, "strategy": "end"|"standard"|"center", "duration": seconds}"""
    if not isinstance(ads, dict):
        raise ChannelError("Configuración de comerciales inválida.")
    if kind(conf) != "schedule":
        raise ChannelError("Los comerciales solo existen en canales con horario.")
    if not ads.get("enabled"):
        conf["commercial_free"] = True
        return
    strategy = ads.get("strategy", "end")
    if strategy not in BREAK_STRATEGIES:
        raise ChannelError("Elige cuándo van los comerciales.")
    try:
        duration = int(ads.get("duration", 120))
    except (TypeError, ValueError):
        raise ChannelError("La duración de la tanda debe ser un número de segundos.")
    if not MIN_BREAK <= duration <= MAX_BREAK:
        raise ChannelError("La tanda de comerciales debe durar entre 15 segundos y 10 minutos.")
    conf.update({
        "commercial_free": False,
        "commercial_dir": f"{channel_dir(conf)}/{COMMERCIAL_DIR}",
        "break_strategy": strategy,
        "break_duration": duration,
    })


def set_logo(conf, logo, filename=None):
    """logo = {"show": bool, "permanent": bool}; filename: name of an uploaded
    logo in the channel's logos folder, or "" to go back to the T-Rex Bites logo."""
    if logo is not None:
        if not isinstance(logo, dict):
            raise ChannelError("Configuración de logo inválida.")
        conf["show_logo"] = bool(logo.get("show", True))
        conf["logo_permanent"] = bool(logo.get("permanent", True))
    if filename is not None:
        if filename:
            conf["logo_dir"] = f"{channel_dir(conf)}/{LOGO_DIR}"
            conf["default_logo"] = filename
        else:
            conf.pop("default_logo", None)
            conf.pop("logo_dir", None)


def _clean_pautas(items, existing=()):
    try:
        return [p for _, p in library._names(items, set(existing), "pauta", MAX_PAUTAS)]
    except library.LibraryError as e:
        raise ChannelError(str(e))


def update_station_conf(conf, stations, long_name, number, ads=None, logo=None, pautas=None,
                        parental=None, allday=None, valid_tags=()):
    conf = copy.deepcopy(conf)
    conf["network_long_name"] = clean_label(long_name, "El nombre del canal")
    conf["channel_number"] = _clean_number(number, stations, own_name=conf["network_name"])
    rename(conf, stations)
    if allday is not None:
        if kind(conf) != "allday":
            raise ChannelError("Este canal tiene horario: se arma en el editor de programación.")
        set_allday(conf, allday, valid_tags)
    if pautas is not None and kind(conf) == "schedule":
        pautas = _clean_pautas(pautas, [p["tag"] for p in channel_pautas(conf)])
        keep = {p["tag"] for p in pautas}
        for block in (b for day in week_blocks(conf).values() for b in day):
            if block.get("pauta") and block["pauta"] not in keep:
                raise ChannelError("Esa pauta está en el horario. Quítala primero de sus bloques.")
        conf.setdefault("trexbites", {})["pautas"] = pautas
    if ads is not None:
        set_ads(conf, ads)
    if logo is not None:
        set_logo(conf, logo)
    if parental is not None:
        conf["parental_controls"] = bool(parental)
    return conf


# ---------- guide channel ----------
GUIDE_NAME = "Guia"


def find_guide(stations):
    for conf in stations:
        if conf.get("network_type") == "guide":
            return conf
    return None


def guide_conf(stations, number, images=(), music_dir=None, has_music=False, messages=None):
    """FieldStation42's cable-style guide: what every channel is showing now and next."""
    own = (find_guide(stations) or {}).get("network_name")
    number = _clean_number(number, stations, own_name=own)
    msgs = [m.strip()[:60] for m in (messages or []) if isinstance(m, str) and m.strip()][:6]
    return {
        "network_name": own or GUIDE_NAME,
        "network_long_name": "Guía de canales",
        "network_type": "guide",
        "channel_number": number,
        "fullscreen": True,
        "width": 720,
        "height": 480,
        "messages": msgs or ["T-Rex Bites\n¡Tu tele de los 2000!", "¿Qué dan ahora?\nMira la guía.",
                             "T-Rex Bites\nCanales para toda la familia."],
        "footer_messages": ["Estás viendo la guía de T-Rex Bites", "Cambia de canal para ver un programa"],
        "images": [str(i) for i in images],
        "play_sound": bool(has_music and music_dir),
        "sound_to_play": str(music_dir) if has_music and music_dir else None,
        "scroll_speed": 1.0,
        "top_bg": "#1b1f3b",
        "bottom_bg": "#262a55",
        "schedule_highlight_fg": "#ffb347",
        "trexbites": {"kind": "guide"},
    }


# ---------- installer helpers ----------

def media_dirs(confs_dir, fs42_dir):
    """Folders that need a sample clip when empty: library categories and
    programs (placeholder), and channel commercial folders (ident)."""
    placeholder, ident = [], []
    for tag, _ in library.content_tags(library.load(fs42_dir)):
        placeholder.append(library.folder(fs42_dir, tag))
    for conf in load_stations(confs_dir):
        for tag, path in station_folders(conf, fs42_dir):
            if tag in (COMMERCIAL_TAG, BUMPS_TAG) or tag.startswith(PAUTA_PREFIX):
                ident.append(path)
    return placeholder, ident


def main():
    parser = argparse.ArgumentParser(description="T-Rex Bites channel folders")
    parser.add_argument("--confs", required=True, help="FieldStation42 confs folder")
    parser.add_argument("--fs42", required=True, help="FieldStation42 folder")
    parser.add_argument("--print-dirs", action="store_true", help="library folders that need a sample video")
    parser.add_argument("--print-bump-dirs", action="store_true", help="channel folders that need the ident")
    args = parser.parse_args()
    placeholder, ident = media_dirs(args.confs, args.fs42)
    for path in (ident if args.print_bump_dirs else placeholder):
        print(path)


if __name__ == "__main__":
    main()
