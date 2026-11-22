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
RESERVED_TAGS = {SIGNOFF, BUMP_DIR}

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
    if not tags:
        return [(None, base)]
    return [(tag, base / tag) for tag in tags]


def week_grid(conf):
    """{day: {hour: tag | "signoff"}} with only the hours that are on air."""
    grid = {}
    for day in DAYS:
        slots = conf.get(day) if isinstance(conf.get(day), dict) else {}
        day_grid = {}
        for hour, slot in slots.items():
            if not (str(hour).isdigit() and isinstance(slot, dict)):
                continue
            if slot.get("event") == SIGNOFF:
                day_grid[str(int(hour))] = SIGNOFF
            elif isinstance(slot.get("tags"), str):
                day_grid[str(int(hour))] = slot["tags"]
            elif isinstance(slot.get("tags"), list) and slot["tags"]:
                day_grid[str(int(hour))] = slot["tags"][0]
        grid[day] = day_grid
    return grid


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
            "schedule": week_grid(conf) if ntype == "standard" else None,
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
    """New channels: on air 7:00-20:00 with their first category, then sign off."""
    day = {str(h): {"tags": first_tag} for h in range(7, 20)}
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


def update_station_conf(conf, stations, long_name, number, categories=None):
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
    return conf


def set_week(conf, week):
    """Replace a standard channel's weekly schedule with week = {day: {hour: tag|"signoff"}}."""
    if conf.get("network_type", "standard") != "standard":
        raise ChannelError("Este canal no usa horario: pasa sus videos todo el día.")
    if not isinstance(week, dict):
        raise ChannelError("Horario inválido.")
    valid = {tag for tag, _ in channel_categories(conf)}
    conf = copy.deepcopy(conf)
    _remember_categories(conf)
    _repair(conf)
    for day in DAYS:
        slots = week.get(day) or {}
        if not isinstance(slots, dict):
            raise ChannelError("Horario inválido.")
        new_day = {}
        for hour, value in slots.items():
            if not str(hour).isdigit() or not 0 <= int(hour) <= 23:
                raise ChannelError("Hora inválida en el horario.")
            if value == SIGNOFF:
                new_day[str(int(hour))] = {"event": SIGNOFF}
            elif value in valid:
                new_day[str(int(hour))] = {"tags": value}
            else:
                raise ChannelError("El horario usa una categoría que no existe.")
        conf[day] = dict(sorted(new_day.items(), key=lambda kv: int(kv[0])))
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
