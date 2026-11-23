"""Read and edit FieldStation42 channel configs, and work out where each channel's videos go.

Standard library only: the installer also runs this module (before the panel's
virtualenv exists) to create the media folders.
"""

import argparse
import copy
import json
import re
import unicodedata
from pathlib import Path

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
UPLOADABLE_TYPES = ("standard", "loop")
SIGNOFF = "signoff"
MAX_CATEGORIES = 12
MAX_NAME_LENGTH = 30

TAG_LABELS = {
    "manana": "Mañana",
    "dibujos": "Dibujos animados",
    "educativo": "Educativos",
    "peliculas": "Películas",
}

# short clips FieldStation42 plays to fill the gaps between programs; scheduled
# channels need at least one (T-Rex Bites puts its own ident there)
BUMP_DIR = "bumps"
# commercials of a scheduled channel; shown in the panel as one more folder
COMMERCIAL_DIR = "comerciales"
COMMERCIAL_TAG = "_comerciales"
# the channel's own logo (FieldStation42's OSD looks in content_dir/logos)
LOGO_DIR = "logos"
LOGO_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif")
# block-specific commercial "pautas": content_dir/pautas/<name>
PAUTAS_DIR = "pautas"
PAUTA_PREFIX = "_pauta/"
# fixed videos played at the start or end of a block: content_dir/fijos
FIXED_DIR = "fijos"
FIXED_TAG = "_fijos"
# the gap-filling clips (cortinillas) shown as an upload folder
BUMPS_TAG = "_cortinillas"
MAX_PROGRAMS = 40
MAX_PAUTAS = 12

# Folder names FieldStation42 reads as "when this may play" hints. A video in
# comerciales/morning/ only plays in the morning; folders can be nested
# (comerciales/prime/saturday/). Programs and pautas can't use these names.
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
HINT_NAMES = ({*WHEN_PARTS, *WHEN_DAYS, *(m.lower() for m in WHEN_MONTHS), *WHEN_MONTHS,
               "q1", "q2", "q3", "q4", "pre", "post", "next"})
RESERVED_TAGS = {SIGNOFF, BUMP_DIR, COMMERCIAL_DIR, LOGO_DIR, PAUTAS_DIR, FIXED_DIR, "next"}

# when commercial breaks happen (FieldStation42's break_strategy)
BREAK_STRATEGIES = {
    "end": "Al final de cada programa",
    "standard": "Repartidos durante el programa",
    "center": "Una tanda a la mitad del programa",
}
MIN_BREAK, MAX_BREAK = 15, 600

# runtime files that FieldStation42's installer puts in place
RUNTIME_MEDIA = {
    "sign_off_video": "runtime/signoff.mp4",
    "off_air_video": "runtime/off_air_pattern.mp4",
    "standby_image": "runtime/standby.png",
    "be_right_back_media": "runtime/brb.png",
}


class ChannelError(ValueError):
    """A change the person asked for that can't be made; the message is shown to them."""


# ---------- names ----------

def slugify(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:40]


def tag_label(tag):
    if tag is None:
        return "Todos los videos"
    if tag == COMMERCIAL_TAG:
        return "📺 Comerciales (todo el canal)"
    if tag == BUMPS_TAG:
        return "🎬 Cortinillas (entre programas)"
    if tag == FIXED_TAG:
        return "📌 Videos fijos (inicio o fin de bloque)"
    if tag.startswith(PAUTA_PREFIX):
        return "📺 Pauta: " + tag[len(PAUTA_PREFIX):].replace("_", " ").capitalize()
    if "/" in tag:
        return " › ".join(tag_label(part) for part in tag.split("/", 1))
    return TAG_LABELS.get(tag, tag.replace("_", " ").capitalize())


def clean_label(text, what="El nombre"):
    text = " ".join(str(text or "").split())
    if not text:
        raise ChannelError(f"{what} no puede quedar vacío.")
    if len(text) > MAX_NAME_LENGTH:
        raise ChannelError(f"{what} puede tener hasta {MAX_NAME_LENGTH} letras.")
    if not slugify(text):
        raise ChannelError(f"{what} necesita al menos una letra o número.")
    return text


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


def _add_tags(value, tags):
    if isinstance(value, str) and value:
        if value not in tags:
            tags.append(value)
    elif isinstance(value, list):
        for item in value:
            _add_tags(item, tags)


def schedule_tags(conf):
    """Tags used by a station's weekly schedule plus its fallback tag."""
    tags = []
    for day in DAYS:
        slots = conf.get(day)
        if not isinstance(slots, dict):
            continue
        for hour in sorted(slots, key=lambda h: int(h) if str(h).isdigit() else 99):
            slot = slots[hour]
            if isinstance(slot, dict):
                _add_tags(slot.get("tags"), tags)
    _add_tags(conf.get("fallback_tag"), tags)
    return tags


def channel_categories(conf):
    """[(tag, label)] for a standard channel: the ones T-Rex Bites saved, then any
    other tag the schedule uses (for channels edited in FieldStation42's console)."""
    if conf.get("network_type", "standard") != "standard":
        return []
    result, seen = [], set()
    stored = (conf.get("trexbites") or {}).get("categories") or []
    for item in stored:
        if isinstance(item, dict) and item.get("tag") and item["tag"] not in seen:
            result.append((item["tag"], item.get("label") or tag_label(item["tag"])))
            seen.add(item["tag"])
    for tag in schedule_tags(conf):
        if "/" in tag:
            continue  # "category/program": a program inside a category
        if tag not in seen:
            result.append((tag, tag_label(tag)))
            seen.add(tag)
    return result


def category_tree(conf):
    """[{"tag", "label", "programs": [{"tag", "label"}]}]: categories and the
    programs inside them (program folders live inside the category folder)."""
    stored = {item["tag"]: item for item in (conf.get("trexbites") or {}).get("categories") or []
              if isinstance(item, dict) and item.get("tag")}
    tree = []
    for tag, label in channel_categories(conf):
        programs = []
        for prog in (stored.get(tag) or {}).get("programs") or []:
            if isinstance(prog, dict) and prog.get("tag"):
                programs.append({"tag": prog["tag"], "label": prog.get("label") or tag_label(prog["tag"])})
        tree.append({"tag": tag, "label": label, "programs": programs})
    return tree


def content_tags(conf):
    """[(tag, label)] every tag a block may use: categories, then "category/program"."""
    result = []
    for cat in category_tree(conf):
        result.append((cat["tag"], cat["label"]))
        for prog in cat["programs"]:
            result.append((f"{cat['tag']}/{prog['tag']}", f"{cat['label']} › {prog['label']}"))
    return result


def channel_pautas(conf):
    """[{"tag", "label"}] the channel's commercial pautas (block-specific ads)."""
    result = []
    for item in (conf.get("trexbites") or {}).get("pautas") or []:
        if isinstance(item, dict) and item.get("tag"):
            result.append({"tag": item["tag"], "label": item.get("label") or tag_label(item["tag"])})
    return result


def station_folders(conf, fs42_dir):
    """(tag, folder) pairs where videos for this station are stored.

    Loop channels and standard channels without tags take videos directly in
    content_dir (tag None). Standard channels with tags get one subfolder per tag,
    which is how FieldStation42 matches schedule slots to videos.
    """
    content_dir = conf.get("content_dir")
    if not content_dir or conf.get("network_type", "standard") not in UPLOADABLE_TYPES:
        return []
    base = Path(content_dir)
    if not base.is_absolute():
        base = Path(fs42_dir) / base
    tags = [tag for tag, _ in content_tags(conf)]
    folders = [(tag, base / tag) for tag in tags] if tags else [(None, base)]
    if conf.get("network_type", "standard") == "standard":
        if ads_enabled(conf):
            folders.append((COMMERCIAL_TAG, base / conf["commercial_dir"]))
            for pauta in channel_pautas(conf):
                folders.append((PAUTA_PREFIX + pauta["tag"], base / PAUTAS_DIR / pauta["tag"]))
        bump = conf.get("bump_dir")
        if isinstance(bump, str) and bump and not Path(bump).is_absolute():
            folders.append((BUMPS_TAG, base / bump))
        folders.append((FIXED_TAG, base / FIXED_DIR))
    return folders


def ads_enabled(conf):
    return (conf.get("network_type", "standard") == "standard"
            and not conf.get("commercial_free", False)
            and isinstance(conf.get("commercial_dir"), str) and bool(conf.get("commercial_dir")))


def ads_settings(conf):
    return {
        "enabled": ads_enabled(conf),
        "strategy": conf.get("break_strategy", "end") if conf.get("break_strategy") in BREAK_STRATEGIES else "end",
        "duration": int(conf.get("break_duration", 120) or 120),
    }


def _content_base(conf, fs42_dir):
    base = Path(conf.get("content_dir") or "")
    return base if base.is_absolute() else Path(fs42_dir) / base


def logo_folder(conf, fs42_dir):
    return _content_base(conf, fs42_dir) / LOGO_DIR


def logo_file(conf, fs42_dir):
    """The channel's uploaded logo, or None (then the T-Rex Bites logo is used)."""
    name = conf.get("default_logo")
    if conf.get("logo_dir") != LOGO_DIR or not isinstance(name, str) or not name:
        return None
    path = logo_folder(conf, fs42_dir) / name
    return path if path.is_file() else None


def logo_settings(conf, fs42_dir):
    return {
        "show": bool(conf.get("show_logo", True)),
        "permanent": bool(conf.get("logo_permanent", True)),
        "custom": logo_file(conf, fs42_dir) is not None,
    }


# Schedule blocks: what the timeline editor works with.
#   {"start": 7, "end": 10, "kind": "show", "tags": ["dibujos", "dibujos/bluey"],
#    "mode": "random"|"order", "breaks": null|"end"|"standard"|"center",
#    "min_minutes": null|int, "max_minutes": null|int,
#    "pauta": null|"juguetes", "start_video": null|"file.mp4", "end_video": null|"file.mp4"}
#   {"start": 20, "end": 21, "kind": "signoff"}
# Hours are whole hours (0-24). In FieldStation42 a block is one slot per hour;
# the hours after the first carry "continued": true so the block can be read back.
# A tag is a category ("dibujos", every video in it and its programs) or one
# program ("dibujos/bluey").
MAX_BLOCK_MINUTES = 600
BLOCK_VIDEO_KEYS = ("start_video", "end_video")


def _fixed_name(path):
    prefix = FIXED_DIR + "/"
    if isinstance(path, str) and path.startswith(prefix) and "/" not in path[len(prefix):]:
        return path[len(prefix):]
    return None


def _slot_content(slot):
    tags = slot.get("tags")
    tags = [tags] if isinstance(tags, str) else [t for t in (tags or []) if isinstance(t, str)]

    def minutes(key):
        value = slot.get(key)
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    pauta = slot.get("commercial_dir")
    prefix = PAUTAS_DIR + "/"
    pauta = pauta[len(prefix):] if isinstance(pauta, str) and pauta.startswith(prefix) else None
    return {
        "kind": "show",
        "tags": tags,
        "mode": "order" if slot.get("sequence") else "random",
        "breaks": slot.get("break_strategy") if slot.get("break_strategy") in BREAK_STRATEGIES else None,
        "min_minutes": minutes("min_duration"),
        "max_minutes": minutes("max_duration"),
        "pauta": pauta,
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
                # FieldStation42's own "continued" slot without tags
                if slot.get("continued") and prev and prev["kind"] == "show" and prev["end"] == hour:
                    prev["end"] = hour + 1
                continue
            content = _slot_content(slot)
            end_video = _fixed_name(slot.get("end_bump"))
            if (slot.get("continued") and prev and prev["kind"] == "show" and prev["end"] == hour
                    and all(prev[k] == content[k] for k in content)):
                prev["end"] = hour + 1
                if end_video:
                    prev["end_video"] = end_video
            else:
                blocks.append({"start": hour, "end": hour + 1, **content,
                               "start_video": _fixed_name(slot.get("start_bump")),
                               "end_video": end_video})
        week[day] = blocks
    return week


def sequence_name(tag):
    """One episode order per category or program, shared by all its "in order" blocks."""
    return "orden-" + tag.replace("/", "-")


def _plain_file(name, what):
    if name in (None, ""):
        return None
    if not isinstance(name, str) or name != Path(name).name or name.startswith("."):
        raise ChannelError(f"{what} inválido.")
    return name


def _clean_block(block, valid_tags, valid_pautas=()):
    if not isinstance(block, dict):
        raise ChannelError("Bloque inválido.")
    try:
        start, end = int(block.get("start")), int(block.get("end"))
    except (TypeError, ValueError):
        raise ChannelError("Las horas de un bloque deben ser números.")
    if not 0 <= start < end <= 24:
        raise ChannelError("Un bloque debe empezar y terminar entre las 0 y las 24 horas.")
    kind = block.get("kind")
    if kind == SIGNOFF:
        return {"start": start, "end": start + 1, "kind": SIGNOFF}
    if kind != "show":
        raise ChannelError("Tipo de bloque inválido.")
    tags = block.get("tags")
    if not isinstance(tags, list) or not tags:
        raise ChannelError("Cada bloque necesita al menos una categoría o programa.")
    if len(set(tags)) != len(tags) or any(t not in valid_tags for t in tags):
        raise ChannelError("Un bloque usa una categoría o programa que no existe.")
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
    return {"start": start, "end": end, "kind": "show", "tags": list(tags), "mode": mode,
            "breaks": breaks, **limits, "pauta": pauta, **videos}


def _block_slot(block):
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
        slot["commercial_dir"] = f"{PAUTAS_DIR}/{block['pauta']}"
    return slot


def set_blocks(conf, week):
    """Replace a standard channel's weekly schedule with {day: [block]}."""
    if conf.get("network_type", "standard") != "standard":
        raise ChannelError("Este canal no usa horario: pasa sus videos todo el día.")
    if not isinstance(week, dict):
        raise ChannelError("Programación inválida.")
    valid = {tag for tag, _ in content_tags(conf)}
    pautas = {p["tag"] for p in channel_pautas(conf)}
    conf = copy.deepcopy(conf)
    _remember_categories(conf)
    _repair(conf)
    for day in DAYS:
        blocks = week.get(day) or []
        if not isinstance(blocks, list):
            raise ChannelError("Programación inválida.")
        cleaned = sorted((_clean_block(b, valid, pautas) for b in blocks), key=lambda b: b["start"])
        for before, after in zip(cleaned, cleaned[1:]):
            if after["start"] < before["end"]:
                raise ChannelError("Hay bloques que se superponen el mismo día.")
        slots = {}
        for block in cleaned:
            if block["kind"] == SIGNOFF:
                slots[str(block["start"])] = {"event": SIGNOFF}
                continue
            slot = _block_slot(block)
            hours = range(block["start"], block["end"])
            for hour in hours:
                this = dict(slot) if hour == block["start"] else {**slot, "continued": True}
                # the fixed video plays once when the block starts, and after the
                # programs of its last hour
                if hour == block["start"] and block["start_video"]:
                    this["start_bump"] = f"{FIXED_DIR}/{block['start_video']}"
                if hour == hours[-1] and block["end_video"]:
                    this["end_bump"] = f"{FIXED_DIR}/{block['end_video']}"
                slots[str(hour)] = this
        conf[day] = dict(sorted(slots.items(), key=lambda kv: int(kv[0])))
    return conf


def duplicate_station_conf(conf, stations, long_name, number, share_videos):
    """A copy of a channel: same categories, schedule, commercials and logo
    settings. share_videos=True plays the same video folders; otherwise the
    copy gets its own (empty) folders."""
    new = copy.deepcopy(conf)
    new["network_long_name"] = clean_label(long_name, "El nombre del canal")
    new["channel_number"] = _clean_number(number, stations)
    new["network_name"] = _unique_network_name(new["network_long_name"], stations)
    if not share_videos:
        new["content_dir"] = f"catalog/{slugify(new['network_name'])}"
    new.pop("schedule_path", None)
    new.pop("catalog_path", None)
    return new


def channel_summaries(confs_dir, fs42_dir):
    channels = []
    for conf in load_stations(confs_dir):
        folders = station_folders(conf, fs42_dir)
        if not folders:
            continue
        ntype = conf.get("network_type", "standard")
        labels = dict(content_tags(conf))
        channels.append({
            "name": conf["network_name"],
            "long_name": conf.get("network_long_name") or conf["network_name"],
            "number": conf.get("channel_number"),
            "type": ntype,
            "categories": category_tree(conf),
            "content": [{"tag": t, "label": l} for t, l in content_tags(conf)],
            "pautas": channel_pautas(conf),
            "blocks": week_blocks(conf) if ntype == "standard" else None,
            "parental": bool(conf.get("parental_controls")),
            "kind": (conf.get("trexbites") or {}).get("kind") or ntype,
            "ads": ads_settings(conf) if ntype == "standard" else None,
            "logo": logo_settings(conf, fs42_dir),
            "folders": [
                {"tag": tag, "label": labels.get(tag, tag_label(tag)), "path": str(path)}
                for tag, path in folders
            ],
        })
    return channels


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


def _clean_names(items, existing, what, reserved, maximum, allow_empty=False):
    """items: labels of new entries, or {"tag", "label"} for ones that already
    exist (renaming keeps the tag, so the videos stay linked). Returns
    [(item, {"tag", "label"})]."""
    if not isinstance(items, list):
        raise ChannelError(f"Lista de {what}s inválida.")
    existing = set(existing)
    result, seen = [], set()
    for item in items:
        if isinstance(item, dict) and item.get("tag") in existing:
            tag, label = item["tag"], clean_label(item.get("label"), f"El nombre de la {what}")
        else:
            label = item.get("label") if isinstance(item, dict) else item
            label = clean_label(label, f"El nombre de la {what}")
            tag = slugify(label)
        if tag in reserved:
            raise ChannelError(f"\"{label}\" es un nombre reservado: elige otro.")
        if tag in seen:
            raise ChannelError(f"\"{label}\" está repetido.")
        seen.add(tag)
        result.append((item, {"tag": tag, "label": label}))
    if not result and not allow_empty:
        raise ChannelError("Un canal con horario necesita al menos una categoría.")
    if len(result) > maximum:
        raise ChannelError(f"Puede haber hasta {maximum} {what}s.")
    return result


def _clean_categories(items, existing=(), existing_programs=None):
    """Categories, each optionally with "programs" (same format). A category
    sent without "programs" keeps the programs it had."""
    existing_programs = existing_programs or {}
    result = []
    for item, cat in _clean_names(items, existing, "categoría", RESERVED_TAGS | HINT_NAMES, MAX_CATEGORIES):
        old = existing_programs.get(cat["tag"], [])
        if isinstance(item, dict) and "programs" in item:
            progs = _clean_names(item["programs"], [p["tag"] for p in old], "programa",
                                 RESERVED_TAGS | HINT_NAMES, MAX_PROGRAMS, allow_empty=True)
            cat["programs"] = [p for _, p in progs]
        else:
            cat["programs"] = [dict(p) for p in old]
        result.append(cat)
    return result


def _clean_pautas(items, existing=()):
    return [p for _, p in _clean_names(items, existing, "pauta", RESERVED_TAGS | HINT_NAMES,
                                       MAX_PAUTAS, allow_empty=True)]


def _unique_network_name(long_name, stations):
    base = "".join(w.capitalize() for w in slugify(long_name).split("_"))[:24] or "Canal"
    taken = {s["network_name"].lower() for s in stations}
    name, n = base, 2
    while name.lower() in taken or name.lower() in ("main_config",):
        name = f"{base}{n}"
        n += 1
    return name


def default_week(first_tag):
    """New channels: one block 7:00-20:00 with their first category, then sign off."""
    day = {"7": {"tags": first_tag}}
    day.update({str(h): {"tags": first_tag, "continued": True} for h in range(8, 20)})
    day["20"] = {"event": SIGNOFF}
    return {d: copy.deepcopy(day) for d in DAYS}


CHANNEL_KINDS = ("standard", "loop", "music")
MUSIC_CATEGORY = "Videos musicales"


def music_week(tag):
    """Music channel: music videos back to back, all day, every day."""
    day = {"0": {"tags": tag, "max_duration": 15}}
    day.update({str(h): {"tags": tag, "max_duration": 15, "continued": True} for h in range(1, 24)})
    return {d: copy.deepcopy(day) for d in DAYS}


def new_station_conf(stations, long_name, number, network_type, category_labels=None):
    """network_type: "standard" (with a schedule), "loop" (plays everything all
    day) or "music" (a scheduled channel set up for music videos, MTV style)."""
    long_name = clean_label(long_name, "El nombre del canal")
    if network_type not in CHANNEL_KINDS:
        raise ChannelError("Tipo de canal inválido.")
    number = _clean_number(number, stations)
    name = _unique_network_name(long_name, stations)
    conf = {
        "network_name": name,
        "network_long_name": long_name,
        "channel_number": number,
        "network_type": "loop" if network_type == "loop" else "standard",
        "content_dir": f"catalog/{slugify(name)}",
    }
    if network_type == "music":
        categories = _clean_categories(category_labels or [MUSIC_CATEGORY])
        conf.update({
            # no clock alignment: one video right after the other
            "schedule_increment": 0,
            "commercial_free": True,
            "fallback_tag": categories[0]["tag"],
            "bump_dir": BUMP_DIR,
            "break_strategy": "end",
            "break_duration": 60,
            **RUNTIME_MEDIA,
            **music_week(categories[0]["tag"]),
            "trexbites": {"categories": categories, "kind": "music"},
        })
    elif network_type == "standard":
        categories = _clean_categories(category_labels or [])
        conf.update({
            "schedule_increment": 30,
            "commercial_free": True,
            "fallback_tag": categories[0]["tag"],
            "bump_dir": BUMP_DIR,
            "break_strategy": "end",
            "break_duration": 120,
            **RUNTIME_MEDIA,
            **default_week(categories[0]["tag"]),
            "trexbites": {"categories": categories},
        })
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


def bump_folder(conf, fs42_dir):
    """Folder with the gap-filling clips of a scheduled channel, or None."""
    if conf.get("network_type", "standard") != "standard" or not conf.get("content_dir"):
        return None
    bump = conf.get("bump_dir")
    if not isinstance(bump, str) or not bump:
        return None
    base = Path(conf["content_dir"])
    if not base.is_absolute():
        base = Path(fs42_dir) / base
    return base / bump if not Path(bump).is_absolute() else Path(bump)


def _repair(conf):
    """Older scheduled channels may lack a bump folder, which FieldStation42 needs."""
    if conf.get("network_type", "standard") == "standard" and not conf.get("bump_dir"):
        conf["bump_dir"] = BUMP_DIR


def _remember_categories(conf):
    """Store the category list in the config so it survives schedule edits."""
    if conf.get("network_type", "standard") == "standard":
        conf.setdefault("trexbites", {})["categories"] = category_tree(conf)


def set_ads(conf, ads):
    """ads = {"enabled": bool, "strategy": "end"|"standard"|"center", "duration": seconds}"""
    if not isinstance(ads, dict):
        raise ChannelError("Configuración de comerciales inválida.")
    if conf.get("network_type", "standard") != "standard":
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
        "commercial_dir": COMMERCIAL_DIR,
        "break_strategy": strategy,
        "break_duration": duration,
    })


def set_logo(conf, logo, filename=None):
    """logo = {"show": bool, "permanent": bool}; filename: name of an uploaded
    logo in content_dir/logos, or "" to go back to the T-Rex Bites logo."""
    if logo is not None:
        if not isinstance(logo, dict):
            raise ChannelError("Configuración de logo inválida.")
        conf["show_logo"] = bool(logo.get("show", True))
        conf["logo_permanent"] = bool(logo.get("permanent", True))
    if filename is not None:
        if filename:
            conf["logo_dir"] = LOGO_DIR
            conf["default_logo"] = filename
        else:
            conf.pop("default_logo", None)
            conf.pop("logo_dir", None)


def update_station_conf(conf, stations, long_name, number, categories=None, ads=None, logo=None,
                        pautas=None, parental=None):
    conf = copy.deepcopy(conf)
    conf["network_long_name"] = clean_label(long_name, "El nombre del canal")
    conf["channel_number"] = _clean_number(number, stations, own_name=conf["network_name"])
    _remember_categories(conf)
    _repair(conf)
    standard = conf.get("network_type", "standard") == "standard"
    in_schedule = schedule_tags({d: conf.get(d) for d in DAYS}) if standard else []
    if standard and categories is not None:
        tree = category_tree(conf)
        categories = _clean_categories(categories, [c["tag"] for c in tree],
                                       {c["tag"]: c["programs"] for c in tree})
        keep = {c["tag"] for c in categories}
        keep |= {f"{c['tag']}/{p['tag']}" for c in categories for p in c["programs"]}
        in_use = [t for t in in_schedule if t not in keep]
        if in_use:
            raise ChannelError(
                f"\"{tag_label(in_use[0])}\" está en el horario. Quítalo primero del horario."
            )
        conf.setdefault("trexbites", {})["categories"] = categories
        if conf.get("fallback_tag") not in keep or "/" in str(conf.get("fallback_tag")):
            conf["fallback_tag"] = categories[0]["tag"]
    if standard and pautas is not None:
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


def main():
    parser = argparse.ArgumentParser(description="T-Rex Bites channel folders")
    parser.add_argument("--confs", required=True, help="FieldStation42 confs folder")
    parser.add_argument("--fs42", required=True, help="FieldStation42 folder")
    parser.add_argument("--print-dirs", action="store_true", help="print one media folder per line")
    parser.add_argument("--print-bump-dirs", action="store_true", help="print one bump folder per line")
    args = parser.parse_args()
    if args.print_bump_dirs:
        for conf in load_stations(args.confs):
            folder = bump_folder(conf, args.fs42)
            if folder:
                print(folder)
        return
    for channel in channel_summaries(args.confs, args.fs42):
        for folder in channel["folders"]:
            # fixed videos are optional; cortinillas are listed by --print-bump-dirs
            if folder["tag"] not in (FIXED_TAG, BUMPS_TAG):
                print(folder["path"])


if __name__ == "__main__":
    main()
