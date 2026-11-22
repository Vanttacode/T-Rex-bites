import importlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFS = REPO / "system" / "defaults" / "confs"


class FakeFS42Stations:
    """Stands in for FieldStation42's /stations API: saves configs the way it does."""

    def __init__(self, confs):
        self.confs = confs
        self.calls = []

    def _path_of(self, name):
        for path in self.confs.glob("*.json"):
            data = json.loads(path.read_text())
            if data.get("station_conf", {}).get("network_name") == name:
                return path
        return None

    async def create_station(self, conf):
        self.calls.append(("create", conf["network_name"]))
        (self.confs / f"{conf['network_name']}.json").write_text(json.dumps({"station_conf": conf}))

    async def update_station(self, name, conf):
        self.calls.append(("update", name))
        self._path_of(name).write_text(json.dumps({"station_conf": conf}))

    async def delete_station(self, name):
        self.calls.append(("delete", name))
        self._path_of(name).unlink()


@pytest.fixture
def env(tmp_path, monkeypatch):
    fs42 = tmp_path / "fs42"
    shutil.copytree(DEFAULT_CONFS, fs42 / "confs")
    (fs42 / "confs" / "main_config.json").write_text(json.dumps({"api_key": "k" * 20}))
    (fs42 / "catalog").mkdir()
    placeholder = tmp_path / "media" / "_bienvenida_trexbites.mp4"
    placeholder.parent.mkdir()
    placeholder.write_bytes(b"sample")
    ident = tmp_path / "media" / "_ident_trexbites.mp4"
    ident.write_bytes(b"ident")
    monkeypatch.setenv("TREXBITES_IDENT", str(ident))
    monkeypatch.setenv("TREXBITES_FS42_DIR", str(fs42))
    monkeypatch.setenv("TREXBITES_STATE", str(tmp_path / "state" / "panel.json"))
    monkeypatch.setenv("TREXBITES_HISTORY", str(tmp_path / "state" / "history.db"))
    monkeypatch.setenv("TREXBITES_PLACEHOLDER", str(placeholder))
    monkeypatch.setenv("TREXBITES_POWER", "none")
    monkeypatch.setenv("TREXBITES_WIFI", "none")
    monkeypatch.setenv("TREXBITES_FS42_URL", "http://127.0.0.1:9")

    from trexbites_panel import app as app_module
    app_module = importlib.reload(app_module)
    fs42_client = app_module.app.state.fs42
    rebuilds, restarts = [], []
    fs42_client.schedule_rebuild = lambda name, restart=False: rebuilds.append((name, restart))
    fs42_client.schedule_restart = lambda: restarts.append(True)
    stations = FakeFS42Stations(fs42 / "confs")
    fs42_client.create_station = stations.create_station
    fs42_client.update_station = stations.update_station
    fs42_client.delete_station = stations.delete_station
    client = TestClient(app_module.app)
    return {"client": client, "fs42": fs42, "rebuilds": rebuilds, "restarts": restarts,
            "stations": stations, "module": app_module}


def login(client, pin="1234"):
    return client.post("/api/login", json={"pin": pin})
