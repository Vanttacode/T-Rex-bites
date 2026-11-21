"""Read FieldStation42 channel configs and work out where each channel's videos go.

Standard library only: the installer also runs this module (before the panel's
virtualenv exists) to create the media folders.
"""

import argparse
import json
from pathlib import Path

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
UPLOADABLE_TYPES = ("standard", "loop")

TAG_LABELS = {
    "manana": "Mañana",
    "dibujos": "Dibujos animados",
    "educativo": "Educativos",
    "peliculas": "Películas",
}


def tag_label(tag):
    if tag is None:
        return "Todos los videos"
    return TAG_LABELS.get(tag, tag.replace("_", " ").capitalize())


def load_stations(confs_dir):
    """Every station_conf in confs_dir, sorted by channel number."""
    stations = []
    for path in sorted(Path(confs_dir).glob("*.json")):
        if path.name == "main_config.json":
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        conf = data.get("station_conf") if isinstance(data, dict) else None
        if isinstance(conf, dict) and "network_name" in conf:
            stations.append(conf)
    stations.sort(key=lambda s: (s.get("channel_number", 0), s["network_name"]))
    return stations


def _add_tags(value, tags):
    if isinstance(value, str) and value:
        tags.add(value)
    elif isinstance(value, list):
        for item in value:
            _add_tags(item, tags)


def station_tags(conf):
    """Tags used by a station's weekly schedule plus its fallback tag."""
    tags = set()
    for day in DAYS:
        slots = conf.get(day)
        if not isinstance(slots, dict):
            continue
        for slot in slots.values():
            if isinstance(slot, dict):
                _add_tags(slot.get("tags"), tags)
    _add_tags(conf.get("fallback_tag"), tags)
    return sorted(tags)


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
    tags = station_tags(conf) if conf.get("network_type", "standard") == "standard" else []
    if not tags:
        return [(None, base)]
    return [(tag, base / tag) for tag in tags]


def channel_summaries(confs_dir, fs42_dir):
    channels = []
    for conf in load_stations(confs_dir):
        folders = station_folders(conf, fs42_dir)
        if not folders:
            continue
        channels.append({
            "name": conf["network_name"],
            "long_name": conf.get("network_long_name") or conf["network_name"],
            "number": conf.get("channel_number"),
            "type": conf.get("network_type", "standard"),
            "folders": [
                {"tag": tag, "label": tag_label(tag), "path": str(path)}
                for tag, path in folders
            ],
        })
    return channels


def main():
    parser = argparse.ArgumentParser(description="T-Rex Bites channel folders")
    parser.add_argument("--confs", required=True, help="FieldStation42 confs folder")
    parser.add_argument("--fs42", required=True, help="FieldStation42 folder")
    parser.add_argument("--print-dirs", action="store_true", help="print one media folder per line")
    args = parser.parse_args()
    for channel in channel_summaries(args.confs, args.fs42):
        for folder in channel["folders"]:
            print(folder["path"])


if __name__ == "__main__":
    main()
