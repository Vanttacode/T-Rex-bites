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
RESERVED_TAGS = {SIGNOFF, BUMP_DIR, COMMERCIAL_DIR, LOGO_DIR}

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
        return "📺 Comerciales"
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
        if tag not in seen:
            result.append((tag, tag_label(tag)))
            seen.add(tag)
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
    tags = [tag for tag, _ in channel_categories(conf)]
    folders = [(tag, base / tag) for tag in tags] if tags else [(None, base)]
    if ads_enabled(conf):
        folders.append((COMMERCIAL_TAG, base / conf["commercial_dir"]))
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
#   {"start": 7, "end": 10, "kind": "show", "tags": ["dibujos"], "mode": "random"|"order",
#    "breaks": null|"end"|"standard"|"center", "min_minutes": null|int, "max_minutes": null|int}
#   {"start": 20, "end": 21, "kind": "signoff"}
# Hours are whole hours (0-24). In FieldStation42 a block is one slot per hour;
# the hours after the first carry "continued": true so the block can be read back.
MAX_BLOCK_MINUTES = 600


def _slot_content(slot):
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
            if (slot.get("continued") and prev and prev["kind"] == "show" and prev["end"] == hour
                    and all(prev[k] == content[k] for k in content)):
                prev["end"] = hour + 1
            else:
                blocks.append({"start": hour, "end": hour + 1, **content})
        week[day] = blocks
    return week


def sequence_name(tag):
    """One episode order per category, shared by all its "in order" blocks."""
    return f"orden-{tag}"


def _clean_block(block, valid_tags):
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
        raise ChannelError("Cada bloque necesita al menos una categoría.")
    if len(set(tags)) != len(tags) or any(t not in valid_tags for t in tags):
        raise ChannelError("Un bloque usa una categoría que no existe.")
    mode = block.get("mode", "random")
    if mode not in ("random", "order"):
        raise ChannelError("Modo de bloque inválido.")
    if mode == "order" and len(tags) != 1:
        raise ChannelError("\"Capítulos en orden\" funciona con una sola categoría.")
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
    return {"start": start, "end": end, "kind": "show", "tags": list(tags), "mode": mode,
            "breaks": breaks, **limits}


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
    return slot


def set_blocks(conf, week):
    """Replace a standard channel's weekly schedule with {day: [block]}."""
    if conf.get("network_type", "standard") != "standard":
        raise ChannelError("Este canal no usa horario: pasa sus videos todo el día.")
    if not isinstance(week, dict):
        raise ChannelError("Programación inválida.")
    valid = {tag for tag, _ in channel_categories(conf)}
    conf = copy.deepcopy(conf)
    _remember_categories(conf)
    _repair(conf)
    for day in DAYS:
        blocks = week.get(day) or []
        if not isinstance(blocks, list):
            raise ChannelError("Programación inválida.")
        cleaned = sorted((_clean_block(b, valid) for b in blocks), key=lambda b: b["start"])
        for before, after in zip(cleaned, cleaned[1:]):
            if after["start"] < before["end"]:
                raise ChannelError("Hay bloques que se superponen el mismo día.")
        slots = {}
        for block in cleaned:
            if block["kind"] == SIGNOFF:
                slots[str(block["start"])] = {"event": SIGNOFF}
                continue
            slot = _block_slot(block)
            slots[str(block["start"])] = slot
            for hour in range(block["start"] + 1, block["end"]):
                slots[str(hour)] = {**slot, "continued": True}
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
        labels = dict(channel_categories(conf))
        channels.append({
            "name": conf["network_name"],
            "long_name": conf.get("network_long_name") or conf["network_name"],
            "number": conf.get("channel_number"),
            "type": ntype,
            "categories": [{"tag": t, "label": l} for t, l in channel_categories(conf)],
            "blocks": week_blocks(conf) if ntype == "standard" else None,
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


def _clean_categories(items, existing=()):
    """items: labels of new categories, or {"tag", "label"} for ones the channel
    already has (renaming keeps the tag, so the videos stay linked)."""
    if not isinstance(items, list):
        raise ChannelError("Lista de categorías inválida.")
    existing = set(existing)
    result, seen = [], set()
    for item in items:
        if isinstance(item, dict) and item.get("tag") in existing:
            tag, label = item["tag"], clean_label(item.get("label"), "El nombre de la categoría")
        else:
            label = item.get("label") if isinstance(item, dict) else item
            label = clean_label(label, "El nombre de la categoría")
            tag = slugify(label)
        if tag in RESERVED_TAGS:
            raise ChannelError("Ese nombre de categoría está reservado.")
        if tag in seen:
            raise ChannelError(f"La categoría \"{label}\" está repetida.")
        seen.add(tag)
        result.append({"tag": tag, "label": label})
    if not result:
        raise ChannelError("Un canal con horario necesita al menos una categoría.")
    if len(result) > MAX_CATEGORIES:
        raise ChannelError(f"Un canal puede tener hasta {MAX_CATEGORIES} categorías.")
    return result


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


def new_station_conf(stations, long_name, number, network_type, category_labels=None):
    long_name = clean_label(long_name, "El nombre del canal")
    if network_type not in UPLOADABLE_TYPES:
        raise ChannelError("Tipo de canal inválido.")
    number = _clean_number(number, stations)
    name = _unique_network_name(long_name, stations)
    conf = {
        "network_name": name,
        "network_long_name": long_name,
        "channel_number": number,
        "network_type": network_type,
        "content_dir": f"catalog/{slugify(name)}",
    }
    if network_type == "standard":
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
        conf.setdefault("trexbites", {})["categories"] = [
            {"tag": t, "label": l} for t, l in channel_categories(conf)
        ]


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


def update_station_conf(conf, stations, long_name, number, categories=None, ads=None, logo=None):
    conf = copy.deepcopy(conf)
    conf["network_long_name"] = clean_label(long_name, "El nombre del canal")
    conf["channel_number"] = _clean_number(number, stations, own_name=conf["network_name"])
    _remember_categories(conf)
    _repair(conf)
    if conf.get("network_type", "standard") == "standard" and categories is not None:
        categories = _clean_categories(categories, [t for t, _ in channel_categories(conf)])
        keep = {c["tag"] for c in categories}
        in_use = [t for t in schedule_tags({d: conf.get(d) for d in DAYS}) if t not in keep]
        if in_use:
            raise ChannelError(
                f"La categoría \"{tag_label(in_use[0])}\" está en el horario. "
                "Quítala primero del horario."
            )
        conf.setdefault("trexbites", {})["categories"] = categories
        if conf.get("fallback_tag") not in keep:
            conf["fallback_tag"] = categories[0]["tag"]
    if ads is not None:
        set_ads(conf, ads)
    if logo is not None:
        set_logo(conf, logo)
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
            print(folder["path"])


if __name__ == "__main__":
    main()
