"""Import videos from a USB stick plugged into the TV computer.

Drives are found with lsblk and mounted with udisksctl (udisks2), which the
polkit rule lets the "tv" user do without a password.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("trexbites.usb")

MAX_LIST = 2000
MAX_DEPTH = 6


class USBError(RuntimeError):
    """Shown to the person as is."""


def _run(cmd, runner, timeout=30):
    try:
        return runner(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise USBError("Este equipo no tiene la herramienta para leer pendrives (udisks2). Actualiza T-Rex Bites.")
    except subprocess.SubprocessError:
        raise USBError("El pendrive no respondió. Sácalo y vuelve a conectarlo.")


def _walk_blocks(devices, parent_removable=False):
    for dev in devices or []:
        removable = parent_removable or bool(dev.get("rm")) or dev.get("tran") == "usb" or bool(dev.get("hotplug"))
        yield dev, removable
        yield from _walk_blocks(dev.get("children"), removable)


def list_drives(runner=subprocess.run):
    """Partitions of removable disks: [{"device", "label", "size", "mounted", "mountpoint"}]."""
    result = _run(["lsblk", "-J", "-b", "-o", "NAME,PATH,RM,HOTPLUG,TRAN,TYPE,FSTYPE,LABEL,SIZE,MOUNTPOINT"], runner)
    try:
        data = json.loads(result.stdout or "{}")
    except ValueError:
        return []
    drives = []
    for dev, removable in _walk_blocks(data.get("blockdevices")):
        if not removable or not dev.get("fstype") or dev.get("type") not in ("part", "disk"):
            continue
        if dev.get("fstype") in ("swap", "LVM2_member", "crypto_LUKS"):
            continue
        mount = dev.get("mountpoint")
        drives.append({
            "device": dev.get("path") or f"/dev/{dev.get('name')}",
            "label": dev.get("label") or "Pendrive",
            "size": int(dev.get("size") or 0),
            "fstype": dev.get("fstype"),
            "mounted": bool(mount),
            "mountpoint": mount,
        })
    return drives


def _check_device(device, runner):
    if device not in {d["device"] for d in list_drives(runner)}:
        raise USBError("No encuentro ese pendrive. ¿Lo sacaste?")


def mount(device, runner=subprocess.run):
    """Mount a drive (read-only is not needed: we only copy from it). Returns the mount point."""
    _check_device(device, runner)
    for d in list_drives(runner):
        if d["device"] == device and d["mountpoint"]:
            return d["mountpoint"]
    result = _run(["udisksctl", "mount", "--no-user-interaction", "-b", device], runner, timeout=60)
    if result.returncode != 0:
        raise USBError("No se pudo abrir el pendrive. Si es de Windows, revisa que no esté dañado.")
    for d in list_drives(runner):
        if d["device"] == device and d["mountpoint"]:
            return d["mountpoint"]
    raise USBError("No se pudo abrir el pendrive.")


def unmount(device, runner=subprocess.run):
    _check_device(device, runner)
    result = _run(["udisksctl", "unmount", "--no-user-interaction", "-b", device], runner, timeout=60)
    if result.returncode != 0 and "not mounted" not in (result.stderr or "").lower():
        raise USBError("No se pudo expulsar: espera a que termine de copiar.")
    _run(["udisksctl", "power-off", "--no-user-interaction", "-b", device], runner, timeout=60)


def list_videos(root, extensions):
    """Video files on the drive: [{"path": relative, "folder", "name", "size"}]."""
    root = Path(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if len(rel_dir.parts) >= MAX_DEPTH:
            dirnames[:] = []
        # skip hidden and system folders (".Trashes", "System Volume Information")
        dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and d != "System Volume Information")
        for name in sorted(filenames, key=str.lower):
            if name.startswith(".") or Path(name).suffix.lower() not in extensions:
                continue
            try:
                size = (Path(dirpath) / name).stat().st_size
            except OSError:
                continue
            found.append({"path": str(rel_dir / name), "folder": str(rel_dir) if str(rel_dir) != "." else "",
                          "name": name, "size": size})
            if len(found) >= MAX_LIST:
                return found
    return found


def resolve(root, rel):
    """A file under the drive's mount point (never outside it)."""
    root = Path(root).resolve()
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file():
        raise USBError("Ese archivo ya no está en el pendrive.")
    return path


class ImportJob:
    """Copies files from the drive to a channel folder, one after the other."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state = {"running": False, "done": 0, "total": 0, "current": None, "errors": [],
                      "bytes_done": 0, "bytes_total": 0, "finished_at": None}

    def status(self):
        with self.lock:
            return dict(self.state, errors=list(self.state["errors"]))

    def start(self, items, on_file=None, on_finish=None):
        """items: [(source Path, target folder Path, unique_path fn)]"""
        with self.lock:
            if self.state["running"]:
                raise USBError("Ya se están copiando videos. Espera a que termine.")
            self.state = {"running": True, "done": 0, "total": len(items), "current": None, "errors": [],
                          "bytes_done": 0, "bytes_total": sum(src.stat().st_size for src, _, _ in items),
                          "finished_at": None}
        thread = threading.Thread(target=self._copy, args=(items, on_file, on_finish), daemon=True)
        thread.start()

    def _copy(self, items, on_file, on_finish):
        for src, folder, make_target in items:
            with self.lock:
                self.state["current"] = src.name
            try:
                folder.mkdir(parents=True, exist_ok=True)
                target = make_target(folder, src.name)
                partial = target.with_name(target.name + ".subiendo")
                with open(src, "rb") as fin, open(partial, "wb") as fout:
                    while True:
                        chunk = fin.read(4 * 1024 * 1024)
                        if not chunk:
                            break
                        fout.write(chunk)
                        with self.lock:
                            self.state["bytes_done"] += len(chunk)
                os.replace(partial, target)
                if on_file:
                    on_file(folder, target)
            except OSError as e:
                log.warning("copy failed for %s: %s", src, e)
                with self.lock:
                    self.state["errors"].append(f"{src.name}: no se pudo copiar")
                try:
                    partial.unlink(missing_ok=True)
                except (OSError, UnboundLocalError):
                    pass
            with self.lock:
                self.state["done"] += 1
        with self.lock:
            self.state.update(running=False, current=None, finished_at=time.time())
        if on_finish:
            on_finish()


def free_space(path):
    return shutil.disk_usage(path).free
