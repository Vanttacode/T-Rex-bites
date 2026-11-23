"""The T-Rex Bites library: one place for every video, shared by all channels.

    catalog/biblioteca/                      content_dir of every channel
      dibujos/                               a category
        bluey/                               a program inside it
        morning/                             a "when" hint folder (see channels.WHEN_*)
      videos_musicales/oliver_tree/
      canales/<channel>/                     what belongs to one channel only:
        comerciales/ pautas/<p>/ bumps/ fijos/ logos/

Categories and programs are subfolders; their display names live in
.trexbites.json next to them. Standard library only (the installer runs it).
"""

import json
import os
import re
import unicodedata
from pathlib import Path

LIBRARY_DIR = "biblioteca"
CONTENT_DIR = f"catalog/{LIBRARY_DIR}"
CHANNELS_DIR = "canales"
INDEX_NAME = ".trexbites.json"
MAX_CATEGORIES = 40
MAX_PROGRAMS = 60
MAX_NAME_LENGTH = 30

DEFAULT_LABELS = {
    "manana": "Mañana",
    "dibujos": "Dibujos animados",
    "educativo": "Educativos",
    "peliculas": "Películas",
    "videos_musicales": "Videos musicales",
}

# FieldStation42 reads these folder names as "when may this play" hints
HINT_NAMES = {
    "morning", "daytime", "prime", "late", "overnight",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    "q1", "q2", "q3", "q4", "pre", "post", "next",
}
RESERVED = HINT_NAMES | {CHANNELS_DIR, "signoff", "bumps", "comerciales", "logos", "pautas", "fijos"}


class LibraryError(ValueError):
    """A change that can't be made; the message is shown to the person."""


def slugify(text):
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")[:40]


def default_label(tag):
    return DEFAULT_LABELS.get(tag, tag.replace("_", " ").capitalize())


def clean_label(text, what):
    text = " ".join(str(text or "").split())
    if not text:
        raise LibraryError(f"{what} no puede quedar vacío.")
    if len(text) > MAX_NAME_LENGTH:
        raise LibraryError(f"{what} puede tener hasta {MAX_NAME_LENGTH} letras.")
    if not slugify(text):
        raise LibraryError(f"{what} necesita al menos una letra o número.")
    return text


def root(fs42_dir):
    return Path(fs42_dir) / CONTENT_DIR


def channel_root(fs42_dir, network_name):
    return root(fs42_dir) / CHANNELS_DIR / slugify(network_name)


def _subdirs(folder):
    try:
        return sorted((p for p in folder.iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=lambda p: p.name.lower())
    except OSError:
        return []


def load(fs42_dir):
    """[{"tag", "label", "programs": [{"tag", "label"}]}]: the saved order and
    names, plus any category or program folder found on disk."""
    base = root(fs42_dir)
    try:
        saved = json.loads((base / INDEX_NAME).read_text(encoding="utf-8")).get("categories") or []
    except (OSError, ValueError, AttributeError):
        saved = []
    tree, seen = [], set()
    for item in saved:
        if not isinstance(item, dict) or not item.get("tag") or item["tag"] in seen or item["tag"] in RESERVED:
            continue
        seen.add(item["tag"])
        progs, pseen = [], set()
        for prog in item.get("programs") or []:
            if isinstance(prog, dict) and prog.get("tag") and prog["tag"] not in pseen and prog["tag"] not in RESERVED:
                pseen.add(prog["tag"])
                progs.append({"tag": prog["tag"], "label": prog.get("label") or default_label(prog["tag"])})
        tree.append({"tag": item["tag"], "label": item.get("label") or default_label(item["tag"]), "programs": progs})
    # folders created outside the panel (a USB copy, FieldStation42's console)
    for folder in _subdirs(base):
        if folder.name in RESERVED or slugify(folder.name) != folder.name:
            continue
        if folder.name not in seen:
            tree.append({"tag": folder.name, "label": default_label(folder.name), "programs": []})
            seen.add(folder.name)
        cat = next(c for c in tree if c["tag"] == folder.name)
        known = {p["tag"] for p in cat["programs"]}
        for sub in _subdirs(folder):
            if sub.name not in RESERVED and sub.name not in known and slugify(sub.name) == sub.name:
                cat["programs"].append({"tag": sub.name, "label": default_label(sub.name)})
    return tree


def save(fs42_dir, tree):
    base = root(fs42_dir)
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / (INDEX_NAME + ".tmp")
    tmp.write_text(json.dumps({"categories": tree}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, base / INDEX_NAME)
    for cat in tree:
        (base / cat["tag"]).mkdir(exist_ok=True)
        for prog in cat["programs"]:
            (base / cat["tag"] / prog["tag"]).mkdir(exist_ok=True)


def content_tags(tree):
    """[(tag, label)]: categories, then "category/program"."""
    result = []
    for cat in tree:
        result.append((cat["tag"], cat["label"]))
        for prog in cat["programs"]:
            result.append((f"{cat['tag']}/{prog['tag']}", f"{cat['label']} › {prog['label']}"))
    return result


def label_of(tree, tag):
    return dict(content_tags(tree)).get(tag, default_label(tag.split("/")[-1]))


def folder(fs42_dir, tag):
    return root(fs42_dir) / tag


def _names(items, existing, what, maximum):
    """items: labels of new entries or {"tag", "label"} for existing ones (a
    rename keeps the tag, so the folder and the videos stay put)."""
    if not isinstance(items, list):
        raise LibraryError(f"Lista de {what}s inválida.")
    result, seen = [], set()
    for item in items:
        if isinstance(item, dict) and item.get("tag") in existing:
            tag, label = item["tag"], clean_label(item.get("label"), f"El nombre de la {what}")
        else:
            label = clean_label(item.get("label") if isinstance(item, dict) else item, f"El nombre de la {what}")
            tag = slugify(label)
        if tag in RESERVED:
            raise LibraryError(f"\"{label}\" es un nombre reservado: elige otro.")
        if tag in seen:
            raise LibraryError(f"\"{label}\" está repetido.")
        seen.add(tag)
        result.append((item, {"tag": tag, "label": label}))
    if len(result) > maximum:
        raise LibraryError(f"Puede haber hasta {maximum} {what}s.")
    return result


def clean_tree(items, current):
    """The new category list; categories sent without "programs" keep theirs."""
    old = {c["tag"]: c for c in current}
    tree = []
    for item, cat in _names(items, set(old), "categoría", MAX_CATEGORIES):
        old_progs = (old.get(cat["tag"]) or {}).get("programs", [])
        if isinstance(item, dict) and "programs" in item:
            cat["programs"] = [p for _, p in _names(item["programs"], {p["tag"] for p in old_progs},
                                                     "programa", MAX_PROGRAMS)]
        else:
            cat["programs"] = [dict(p) for p in old_progs]
        tree.append(cat)
    return tree


def removed_tags(old_tree, new_tree):
    new = {t for t, _ in content_tags(new_tree)}
    return [t for t, _ in content_tags(old_tree) if t not in new]
