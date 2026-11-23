"""Video tools for the library: duration, thumbnails, and converting videos so
an old computer (and a phone's browser) plays them smoothly, at an even volume.

Uses ffprobe and ffmpeg, which T-Rex Bites installs with FieldStation42.
"""

import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("trexbites.media")

# videos the TV and every browser play without trouble
GOOD_VIDEO_CODECS = {"h264"}
GOOD_AUDIO_CODECS = {"aac", "mp3"}
GOOD_CONTAINERS = {".mp4", ".m4v"}
MAX_HEIGHT = 720
# EBU R128 loudness: every video at the same volume (TV broadcast standard)
LOUDNORM = "loudnorm=I=-16:TP=-1.5:LRA=11"
CONVERTED_MARK = "trexbites"
PROBE_TIMEOUT = 30
THUMB_WIDTH = 240


def _has(tool):
    return shutil.which(tool) is not None


class MediaInfo:
    """ffprobe results cached by path, size and modification time."""

    def __init__(self, cache_path, runner=subprocess.run):
        self.cache_path = Path(cache_path)
        self._run = runner
        self._lock = threading.Lock()
        self._cache = None

    def _load(self):
        if self._cache is None:
            try:
                self._cache = json.loads(self.cache_path.read_text())
            except (OSError, ValueError):
                self._cache = {}
        return self._cache

    def _save(self):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache))
            os.replace(tmp, self.cache_path)
        except OSError:
            pass

    @staticmethod
    def _key(path, st):
        return f"{path}|{st.st_size}|{int(st.st_mtime)}"

    def cached(self, path):
        try:
            st = Path(path).stat()
        except OSError:
            return None
        with self._lock:
            return self._load().get(self._key(path, st))

    def probe(self, path):
        """{"duration": seconds, "vcodec", "acodec", "height", "converted"} or None."""
        path = Path(path)
        hit = self.cached(path)
        if hit is not None:
            return hit
        if not _has("ffprobe"):
            return None
        try:
            result = self._run(
                ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                capture_output=True, text=True, timeout=PROBE_TIMEOUT)
            data = json.loads(result.stdout or "{}")
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        info = {"duration": None, "vcodec": None, "acodec": None, "height": None, "converted": False}
        try:
            info["duration"] = round(float(data.get("format", {}).get("duration")))
        except (TypeError, ValueError):
            pass
        tags = {k.lower(): v for k, v in (data.get("format", {}).get("tags") or {}).items()}
        info["converted"] = CONVERTED_MARK in str(tags.get("comment", ""))
        for stream in data.get("streams") or []:
            if stream.get("codec_type") == "video" and not info["vcodec"]:
                if (stream.get("disposition") or {}).get("attached_pic"):
                    continue
                info["vcodec"] = stream.get("codec_name")
                info["height"] = stream.get("height")
            elif stream.get("codec_type") == "audio" and not info["acodec"]:
                info["acodec"] = stream.get("codec_name")
        try:
            st = path.stat()
        except OSError:
            return info
        with self._lock:
            self._load()[self._key(path, st)] = info
            self._save()
        return info


def needs_video_conversion(path, info):
    if not info or not info.get("vcodec"):
        return False
    return (info["vcodec"] not in GOOD_VIDEO_CODECS
            or (info.get("height") or 0) > MAX_HEIGHT
            or Path(path).suffix.lower() not in GOOD_CONTAINERS)


def ffmpeg_command(src, dst, info, convert_video, normalize):
    """The ffmpeg call that makes dst from src, or None when nothing is needed."""
    video = convert_video and needs_video_conversion(src, info)
    audio_bad = info.get("acodec") is not None and info["acodec"] not in GOOD_AUDIO_CODECS
    audio = (normalize or audio_bad or video) and info.get("acodec") is not None
    if not video and not audio:
        return None
    cmd = ["nice", "-n", "19", "ffmpeg", "-hide_banner", "-nostdin", "-y", "-i", str(src),
           "-map", "0:v:0?", "-map", "0:a:0?", "-sn", "-dn"]
    if video:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-vf", f"scale=-2:'min({MAX_HEIGHT},ih)'"]
    else:
        cmd += ["-c:v", "copy"]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-ac", "2"]
        if normalize:
            cmd += ["-af", LOUDNORM]
    else:
        cmd += ["-c:a", "copy"]
    cmd += ["-movflags", "+faststart", "-metadata", f"comment={CONVERTED_MARK}", "-f", "mp4", str(dst)]
    return cmd


class Converter:
    """One video at a time, in the background, at the lowest CPU priority."""

    def __init__(self, info, settings, on_done=None, runner=subprocess.run):
        self.info = info
        self.settings = settings  # callable -> {"convert": bool, "normalize": bool}
        self.on_done = on_done    # callable(path) after a file was replaced
        self._run = runner
        self.queue = deque()
        self.current = None
        self.failed = {}
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._thread = None

    def status(self):
        with self._lock:
            return {"current": str(self.current) if self.current else None,
                    "waiting": [str(p) for p in self.queue], "failed": dict(self.failed)}

    def add(self, path):
        path = Path(path)
        with self._lock:
            if path in self.queue or path == self.current:
                return
            self.queue.append(path)
        self._wake.set()
        self._start()

    def _start(self):
        if self._thread and self._thread.is_alive():
            return
        if not _has("ffmpeg"):
            return
        self._thread = threading.Thread(target=self._worker, name="converter", daemon=True)
        self._thread.start()

    def _worker(self):
        while True:
            with self._lock:
                path = self.queue.popleft() if self.queue else None
                self.current = path
            if path is None:
                self._wake.clear()
                if not self._wake.wait(timeout=300):
                    return
                continue
            try:
                self.process(path)
            except Exception as e:  # one bad file must not stop the rest
                log.exception("conversion failed for %s", path)
                self.failed[str(path)] = str(e)[:200]
            finally:
                with self._lock:
                    self.current = None

    def process(self, path):
        """Convert one file in place (the result is always .mp4). Returns the new path or None."""
        path = Path(path)
        if not path.is_file():
            return None
        settings = self.settings()
        info = self.info.probe(path)
        if not info or info.get("converted"):
            return None
        tmp = path.with_name(path.stem + ".mp4.convirtiendo")
        cmd = ffmpeg_command(path, tmp, info, settings.get("convert"), settings.get("normalize"))
        if cmd is None:
            return None
        log.info("converting %s", path)
        result = self._run(cmd, capture_output=True, text=True, timeout=6 * 3600)
        if result.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError((result.stderr or "ffmpeg falló").strip().splitlines()[-1:] or "ffmpeg falló")
        target = path.with_suffix(".mp4")
        if target != path and target.exists():
            target = path.with_name(f"{path.stem} (convertido).mp4")
        os.replace(tmp, target)
        if target != path:
            path.unlink(missing_ok=True)
        self.failed.pop(str(path), None)
        if self.on_done:
            self.on_done(target)
        return target


class Thumbnails:
    def __init__(self, cache_dir, runner=subprocess.run):
        self.cache_dir = Path(cache_dir)
        self._run = runner

    def get(self, path, duration=None):
        """Path to a small JPEG of the video (made on first use), or None."""
        path = Path(path)
        try:
            st = path.stat()
        except OSError:
            return None
        key = hashlib.sha1(f"{path}|{st.st_size}|{int(st.st_mtime)}".encode()).hexdigest()
        thumb = self.cache_dir / f"{key}.jpg"
        if thumb.is_file():
            return thumb
        if not _has("ffmpeg"):
            return None
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        at = max(1, min(60, int((duration or 20) * 0.1)))
        try:
            self._run(["nice", "-n", "10", "ffmpeg", "-hide_banner", "-nostdin", "-y", "-ss", str(at),
                       "-i", str(path), "-frames:v", "1", "-vf", f"scale={THUMB_WIDTH}:-2", "-q:v", "5",
                       str(thumb)], capture_output=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        return thumb if thumb.is_file() else None

    def prune(self, max_files=5000):
        try:
            files = sorted(self.cache_dir.glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        except OSError:
            return
        for old in files[:-max_files]:
            old.unlink(missing_ok=True)


def wait_until_stable(path, seconds=2, timeout=30):
    """True once a file stops growing (a copy in progress finished)."""
    end = time.monotonic() + timeout
    last = -1
    while time.monotonic() < end:
        try:
            size = Path(path).stat().st_size
        except OSError:
            return False
        if size == last:
            return True
        last = size
        time.sleep(seconds)
    return False
