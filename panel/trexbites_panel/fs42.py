"""Small client for the FieldStation42 web API running on the same machine."""

import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import quote

import httpx

log = logging.getLogger("trexbites.fs42")

REMOTE_ACTIONS = {
    "up": ("GET", "/player/channels/up"),
    "down": ("GET", "/player/channels/down"),
    "guide": ("POST", "/player/channels/guide"),
    "volume_up": ("POST", "/player/volume/up"),
    "volume_down": ("POST", "/player/volume/down"),
    "mute": ("POST", "/player/volume/mute"),
}

TASK_TIMEOUT = 60 * 60
POLL_SECONDS = 3
REBUILD_DELAY = 5


class FS42Error(Exception):
    pass


class FS42Client:

    def __init__(self, base_url, fs42_dir):
        self.base_url = base_url.rstrip("/")
        self.fs42_dir = Path(fs42_dir)
        self.rebuilds = {}
        self._pending = {}
        self._dirty = set()
        self._restart_wanted = False
        self._restart_task = None

    def _api_key(self):
        # read on every call: FieldStation42 owns this file and may change the key
        try:
            conf = json.loads((self.fs42_dir / "confs" / "main_config.json").read_text(encoding="utf-8"))
            return conf.get("api_key") or None
        except (OSError, ValueError):
            return None

    async def request(self, method, path, timeout=10, body=None):
        headers = {}
        key = self._api_key()
        if key:
            headers["x-api-key"] = key
        try:
            async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
                resp = await client.request(method, path, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise FS42Error(f"La tele no responde ({e.__class__.__name__}).") from e
        if resp.status_code >= 400:
            detail = ""
            try:
                detail = resp.json().get("detail") or ""
            except (ValueError, AttributeError):
                pass
            raise FS42Error(f"La tele respondió con error {resp.status_code}. {detail}".strip())
        try:
            return resp.json()
        except ValueError:
            return {}

    # ---------- remote control ----------

    async def remote(self, action, channel=None):
        if action == "channel":
            if channel is None or not 0 <= channel <= 999:
                raise ValueError("Número de canal inválido.")
            return await self.request("GET", f"/player/channels/{channel}")
        if action not in REMOTE_ACTIONS:
            raise ValueError("Botón desconocido.")
        method, path = REMOTE_ACTIONS[action]
        return await self.request(method, path)

    async def status(self):
        return await self.request("GET", "/player/status")

    # ---------- channel configs (FieldStation42 validates and saves them) ----------

    async def create_station(self, conf):
        await self.request("POST", "/stations", body={"station_conf": conf}, timeout=30)

    async def update_station(self, network_name, conf):
        await self.request("PUT", f"/stations/{quote(network_name)}", body={"station_conf": conf}, timeout=30)

    async def delete_station(self, network_name):
        await self.request("DELETE", f"/stations/{quote(network_name)}", timeout=30)

    # ---------- rebuilding schedules ----------

    async def _run_task(self, start_path, status_path):
        started = await self.request("POST", start_path, timeout=30)
        task_id = started.get("task_id")
        if not task_id:
            raise FS42Error(started.get("error") or "No se pudo iniciar la tarea.")
        waited = 0
        while waited < TASK_TIMEOUT:
            await asyncio.sleep(POLL_SECONDS)
            waited += POLL_SECONDS
            state = await self.request("GET", f"{status_path}/{task_id}")
            if state.get("status") == "done":
                return
            if state.get("status") == "error" or "error" in state:
                raise FS42Error((state.get("log") or state.get("error") or "Error")[-500:])
        raise FS42Error("La tarea tardó demasiado.")

    async def rebuild_channel(self, network_name):
        """Rescan a channel's videos, then rebuild its schedule from now on."""
        self.rebuilds[network_name] = {"status": "running", "detail": ""}
        try:
            name = quote(network_name)
            await self._run_task(f"/build/catalog/{name}", "/build/catalog/status")
            await self._run_task(f"/build/schedule/reset/{name}", "/build/schedule/reset/status")
            self.rebuilds[network_name] = {"status": "done", "detail": ""}
        except FS42Error as e:
            log.warning("rebuild of %s failed: %s", network_name, e)
            self.rebuilds[network_name] = {"status": "error", "detail": str(e)}

    def _busy(self):
        """True while a rebuild other than the calling one is still waiting or running."""
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        return any(not task.done() and task is not current for task in self._pending.values())

    def schedule_rebuild(self, network_name, restart=False):
        """Rebuild a channel shortly. Changes that arrive while a rebuild is
        already waiting or running are picked up by one more pass afterwards.

        restart=True also restarts the player once every rebuild is done: the
        player only learns about new, deleted or renumbered channels on start."""
        if restart:
            self._restart_wanted = True
        if network_name in self._pending and not self._pending[network_name].done():
            self._dirty.add(network_name)
            return
        self.rebuilds[network_name] = {"status": "waiting", "detail": ""}

        async def delayed():
            while True:
                await asyncio.sleep(REBUILD_DELAY)
                self._dirty.discard(network_name)
                await self.rebuild_channel(network_name)
                if network_name not in self._dirty:
                    break
            self._maybe_restart()

        self._pending[network_name] = asyncio.get_running_loop().create_task(delayed())

    def schedule_restart(self):
        self._restart_wanted = True
        if not self._busy():
            self._maybe_restart()

    def _maybe_restart(self):
        if not self._restart_wanted or self._busy():
            return
        if self._restart_task and not self._restart_task.done():
            return
        self._restart_wanted = False

        async def restart():
            await asyncio.sleep(REBUILD_DELAY)
            if self._busy():
                self._restart_wanted = True
                return
            try:
                await self.request("POST", "/manage/restart", timeout=30)
                self.rebuilds["_player"] = {"status": "done", "detail": ""}
            except FS42Error as e:
                log.warning("player restart failed: %s", e)
                self.rebuilds["_player"] = {"status": "error", "detail": str(e)}

        self.rebuilds["_player"] = {"status": "waiting", "detail": ""}
        self._restart_task = asyncio.get_running_loop().create_task(restart())
