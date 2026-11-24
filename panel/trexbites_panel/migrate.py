"""Move channels made before the shared library (v0.5 and earlier) into it.

Before: every channel had its own folder (catalog/trex_tv/dibujos, ...).
After:  one library (catalog/biblioteca/dibujos, ...) shared by all channels,
        plus catalog/biblioteca/canales/<channel>/ for what is only theirs.

Files are moved (renamed on the same disk), never copied or deleted, so it is
fast and nothing is lost. The channel configs are copied to
confs/respaldo-antes-de-biblioteca/ first. Running it again does nothing.

    python3 -m trexbites_panel.migrate --confs <fs42>/confs --fs42 <fs42>
"""

import argparse
import json
import os
import shutil
from pathlib import Path

from . import channels, library

PLACEHOLDERS = {"_bienvenida_trexbites.mp4", "_ident_trexbites.mp4"}
VIDEO_EXTENSIONS = {".mp4", ".m4v", ".mkv", ".avi", ".mov", ".webm", ".mpg", ".mpeg", ".ts", ".wmv", ".flv"}
BACKUP_DIR = "respaldo-antes-de-biblioteca"


def log(msg):
    print(f"[biblioteca] {msg}", flush=True)


def _unique(path):
    if not path.exists():
        return path
    n = 2
    while True:
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def merge_move(src, dest):
    """Move src (file or folder) to dest; folders that already exist are merged."""
    if not src.exists():
        return
    if src.is_dir() and dest.is_dir():
        for child in sorted(src.iterdir()):
            merge_move(child, dest / child.name)
        try:
            src.rmdir()
        except OSError:
            pass
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if src.is_file() and src.name in PLACEHOLDERS:
            src.unlink()  # a second sample clip adds nothing
            return
        dest = _unique(dest)
    os.rename(src, dest)


def _remove_empty_dirs(folder):
    if not folder.is_dir():
        return
    for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                pass
    try:
        folder.rmdir()
    except OSError:
        pass


def _has_videos(folder):
    return folder.is_dir() and any(
        p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS and p.name not in PLACEHOLDERS
        for p in folder.rglob("*"))


def _map_tag(tag, mapping):
    if not isinstance(tag, str):
        return tag
    head, _, rest = tag.partition("/")
    new = mapping.get(head, head)
    return f"{new}/{rest}" if rest else new


def _old_categories(conf):
    tags = []
    for item in (conf.get("trexbites") or {}).get("categories") or []:
        if isinstance(item, dict) and item.get("tag"):
            tags.append(item)
    known = {c["tag"] for c in tags}
    for tag in channels.schedule_tags(conf) + [conf.get("fallback_tag")]:
        if isinstance(tag, str) and tag:
            head = tag.split("/")[0]
            if head not in known:
                tags.append({"tag": head, "label": library.default_label(head), "programs": []})
                known.add(head)
    return tags


def migrate_station(conf, fs42_dir, tree, moved, taken_dirs):
    """Move one old-style channel into the library. Returns the new conf."""
    fs42_dir = Path(fs42_dir)
    base = Path(conf.get("content_dir") or "")
    base = base if base.is_absolute() else fs42_dir / base
    lib = library.root(fs42_dir)
    long_name = conf.get("network_long_name") or conf["network_name"]
    slug = library.slugify(conf["network_name"]) or "canal"
    own = f"{library.CHANNELS_DIR}/{slug}"
    n = 2
    while own in taken_dirs or (lib / own).exists():
        own = f"{library.CHANNELS_DIR}/{slug}{n}"
        n += 1
    taken_dirs.add(own)
    known = {c["tag"]: c for c in tree}
    mapping = {}

    def claim(tag, label, src):
        """The library tag that holds src's videos (shared folders map to the same tag)."""
        # channels duplicated with "same videos" shared one folder: same tag
        key = os.path.realpath(src)
        if key in moved:
            return moved[key]
        target, label_out = tag, label
        # an existing category is reused only while it is empty and unclaimed
        busy = target in moved.values() or _has_videos(lib / target)
        if busy or target in library.RESERVED:
            target = library.slugify(f"{tag}_{slug}")
            label_out = f"{label} ({long_name})"[:library.MAX_NAME_LENGTH]
        if target not in known:
            entry = {"tag": target, "label": label_out, "programs": []}
            tree.append(entry)
            known[target] = entry
        else:
            known[target]["label"] = label_out  # the channel's own name for it
        if src.exists():
            log(f"{src} -> {lib / target}")
            merge_move(src, lib / target)
        moved[key] = target
        return target

    old_type = conf.get("network_type")
    old_kind = (conf.get("trexbites") or {}).get("kind")
    new = {k: v for k, v in conf.items() if k not in channels.DAYS}
    # the logo first: it must not end up inside a category
    if conf.get("logo_dir"):
        src = Path(conf["logo_dir"])
        src = src if src.is_absolute() else base / src
        merge_move(src, lib / own / channels.LOGO_DIR)
        new["logo_dir"] = f"{own}/{channels.LOGO_DIR}"
    if old_type == "loop":
        # everything the loop channel had becomes one category named after it
        src_tag = library.slugify(long_name) or slug
        target = claim(src_tag, long_name, base)
        week = {d: {"0": {"tags": target}, **{str(h): {"tags": target, "continued": True} for h in range(1, 24)}}
                for d in channels.DAYS}
        new.update(week)
        new.update({"network_type": "standard", "schedule_increment": 0, "commercial_free": True,
                    "fallback_tag": target, "break_strategy": "end", "break_duration": 120,
                    **{k: v for k, v in channels.RUNTIME_MEDIA.items() if k not in new}})
        kind = "allday"
    else:
        # the channel's own folders first, so they don't end up as categories
        for sub, old in ((channels.COMMERCIAL_DIR, conf.get("commercial_dir") or channels.COMMERCIAL_DIR),
                         (channels.PAUTAS_DIR, channels.PAUTAS_DIR),
                         (channels.BUMP_DIR, conf.get("bump_dir") or channels.BUMP_DIR),
                         (channels.FIXED_DIR, channels.FIXED_DIR)):
            src = Path(old) if Path(old).is_absolute() else base / old
            if src.exists() and src.resolve() != (lib / own / sub).resolve():
                merge_move(src, lib / own / sub)
        for cat in _old_categories(conf):
            target = claim(cat["tag"], cat.get("label") or library.default_label(cat["tag"]), base / cat["tag"])
            mapping[cat["tag"]] = target
            have = {p["tag"] for p in known[target]["programs"]}
            for prog in cat.get("programs") or []:
                if isinstance(prog, dict) and prog.get("tag") and prog["tag"] not in have:
                    known[target]["programs"].append({"tag": prog["tag"], "label": prog.get("label") or prog["tag"]})
        for day in channels.DAYS:
            slots = {}
            for hour, slot in (conf.get(day) or {}).items():
                if not isinstance(slot, dict):
                    continue
                slot = dict(slot)
                if "tags" in slot:
                    slot["tags"] = ([_map_tag(t, mapping) for t in slot["tags"]] if isinstance(slot["tags"], list)
                                    else _map_tag(slot["tags"], mapping))
                    if "sequence" in slot:
                        first = slot["tags"][0] if isinstance(slot["tags"], list) else slot["tags"]
                        slot["sequence"] = channels.sequence_name(first)
                for key, sub in (("commercial_dir", channels.PAUTAS_DIR), ("start_bump", channels.FIXED_DIR),
                                 ("end_bump", channels.FIXED_DIR)):
                    value = slot.get(key)
                    if isinstance(value, str) and value.startswith(sub + "/"):
                        slot[key] = f"{own}/{value}"
                slots[hour] = slot
            new[day] = slots
        if conf.get("fallback_tag"):
            new["fallback_tag"] = _map_tag(conf["fallback_tag"], mapping).split("/")[0]
        kind = "allday" if old_kind == "music" else "schedule"
        if not new.get("commercial_free", False) and conf.get("commercial_dir"):
            new["commercial_dir"] = f"{own}/{channels.COMMERCIAL_DIR}"
        else:
            new.pop("commercial_dir", None)
            new["commercial_free"] = True  # FieldStation42 fails without a commercials folder
    for key, value in channels.RUNTIME_MEDIA.items():
        new.setdefault(key, value)  # off-air and sign-off videos: needed outside the blocks
    new["content_dir"] = library.CONTENT_DIR
    new["bump_dir"] = f"{own}/{channels.BUMP_DIR}"
    pautas = (conf.get("trexbites") or {}).get("pautas") or []
    new["trexbites"] = {"kind": kind, "folder": own, "pautas": pautas}
    for key in ("schedule_path", "catalog_path"):
        new.pop(key, None)
    if base.exists() and base.resolve() != lib.resolve() and lib.resolve() not in base.resolve().parents:
        # anything left in the old folder (videos outside any category) is kept
        leftovers = [p for p in base.rglob("*") if p.is_file() and p.name not in PLACEHOLDERS]
        if leftovers:
            target = claim(library.slugify(f"otros_{slug}"), f"Otros ({long_name})"[:30], base)
            log(f"{len(leftovers)} archivos sueltos de {long_name} -> {target}")
        else:
            _remove_empty_dirs(base)
            if base.exists():
                for p in base.rglob("*"):
                    if p.is_file() and p.name in PLACEHOLDERS:
                        p.unlink()
                _remove_empty_dirs(base)
    return new


def _drop_extra_placeholders(lib):
    for folder in [lib] + [p for p in lib.rglob("*") if p.is_dir()]:
        for name in PLACEHOLDERS:
            sample = folder / name
            others = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
                      and p.name not in PLACEHOLDERS] if folder.is_dir() else []
            if sample.exists() and others:
                sample.unlink()


def migrate(confs_dir, fs42_dir):
    confs_dir, fs42_dir = Path(confs_dir), Path(fs42_dir)
    files = list(channels._station_files(confs_dir))
    todo = [(path, conf) for path, conf in files
            if conf.get("network_type") in ("standard", "loop") and conf.get("content_dir") != library.CONTENT_DIR]
    if not todo:
        return 0
    # lower channel numbers first: the main channel keeps its category names
    todo.sort(key=lambda item: (item[1].get("channel_number") or 99, item[1]["network_name"]))
    backup = confs_dir / BACKUP_DIR
    backup.mkdir(exist_ok=True)
    for path, _ in files:
        if not (backup / path.name).exists():
            shutil.copy2(path, backup / path.name)
    log(f"configuración copiada en {backup}")
    lib = library.root(fs42_dir)
    lib.mkdir(parents=True, exist_ok=True)
    tree = library.load(fs42_dir)
    moved, taken = {}, set()
    for path, conf in todo:
        log(f"mudando el canal {conf.get('network_long_name') or conf['network_name']}")
        new = migrate_station(conf, fs42_dir, tree, moved, taken)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"station_conf": new}, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    library.save(fs42_dir, tree)
    _drop_extra_placeholders(lib)
    log(f"{len(todo)} canales mudados a la biblioteca")
    return len(todo)


def sync_names(confs_dir):
    """Older channels used an internal id ("DinoLoop") that the TV showed on
    screen; the visible name ("Oliver TV") replaces it."""
    files = list(channels._station_files(Path(confs_dir)))
    stations = [conf for _, conf in files]
    changed = 0
    for path, conf in files:
        if not channels.is_channel(conf):
            continue
        before = conf["network_name"]
        channels.rename(conf, stations)
        if conf["network_name"] != before or "folder" not in (conf.get("trexbites") or {}):
            log(f"el canal {before} ahora se llama {conf['network_name']} en la tele")
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"station_conf": conf}, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
            changed += 1
    return changed


def main():
    parser = argparse.ArgumentParser(description="Move T-Rex Bites channels into the shared library")
    parser.add_argument("--confs", required=True)
    parser.add_argument("--fs42", required=True)
    args = parser.parse_args()
    migrate(args.confs, args.fs42)
    sync_names(args.confs)


if __name__ == "__main__":
    main()
