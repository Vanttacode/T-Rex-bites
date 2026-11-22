"""Panel settings stored on disk: the parent PIN and the session secret."""

import hashlib
import hmac
import json
import os
import secrets
import threading
from pathlib import Path

DEFAULT_PIN = "1234"
PBKDF2_ROUNDS = 200_000


def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt), PBKDF2_ROUNDS).hex()


def valid_pin_format(pin):
    return isinstance(pin, str) and pin.isdigit() and 4 <= len(pin) <= 8


class PanelState:

    def __init__(self, path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if all(k in data for k in ("secret", "pin_salt", "pin_hash", "session_version")):
                return data
        except (OSError, ValueError):
            pass
        data = {"secret": secrets.token_hex(32), "session_version": 1}
        data.update(self._pin_fields(DEFAULT_PIN, is_default=True))
        self._write(data)
        return data

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, self.path)

    @staticmethod
    def _pin_fields(pin, is_default):
        salt = secrets.token_hex(16)
        return {"pin_salt": salt, "pin_hash": _hash_pin(pin, salt), "pin_is_default": is_default}

    @property
    def pin_is_default(self):
        return bool(self._data.get("pin_is_default"))

    def check_pin(self, pin):
        if not isinstance(pin, str):
            return False
        expected = self._data["pin_hash"]
        return hmac.compare_digest(_hash_pin(pin, self._data["pin_salt"]), expected)

    def set_pin(self, new_pin):
        if not valid_pin_format(new_pin):
            raise ValueError("El PIN debe tener entre 4 y 8 números.")
        with self._lock:
            data = dict(self._data)
            data.update(self._pin_fields(new_pin, is_default=(new_pin == DEFAULT_PIN)))
            # changing the PIN logs out every other phone and computer
            data["session_version"] = data["session_version"] + 1
            self._write(data)
            self._data = data

    def get(self, key, default=None):
        """Other panel settings (bedtime, power override), stored next to the PIN."""
        return self._data.get("settings", {}).get(key, default)

    def set(self, key, value):
        with self._lock:
            data = dict(self._data)
            settings = dict(data.get("settings", {}))
            if value is None:
                settings.pop(key, None)
            else:
                settings[key] = value
            data["settings"] = settings
            self._write(data)
            self._data = data

    def session_token(self):
        msg = f"trexbites-session-{self._data['session_version']}".encode()
        return hmac.new(bytes.fromhex(self._data["secret"]), msg, hashlib.sha256).hexdigest()

    def valid_session(self, token):
        return isinstance(token, str) and hmac.compare_digest(token, self.session_token())
