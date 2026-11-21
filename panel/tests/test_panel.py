import importlib
import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CONFS = REPO / "system" / "defaults" / "confs"


@pytest.fixture
def env(tmp_path, monkeypatch):
    fs42 = tmp_path / "fs42"
    shutil.copytree(DEFAULT_CONFS, fs42 / "confs")
    (fs42 / "confs" / "main_config.json").write_text(json.dumps({"api_key": "k" * 20}))
    (fs42 / "catalog").mkdir()
    monkeypatch.setenv("TREXBITES_FS42_DIR", str(fs42))
    monkeypatch.setenv("TREXBITES_STATE", str(tmp_path / "state" / "panel.json"))
    monkeypatch.setenv("TREXBITES_FS42_URL", "http://127.0.0.1:9")

    from trexbites_panel import app as app_module
    app_module = importlib.reload(app_module)
    rebuilds = []
    app_module.app.state.fs42.schedule_rebuild = rebuilds.append
    client = TestClient(app_module.app)
    return {"client": client, "fs42": fs42, "rebuilds": rebuilds, "module": app_module}


def login(client, pin="1234"):
    return client.post("/api/login", json={"pin": pin})


def test_index_is_public(env):
    resp = env["client"].get("/")
    assert resp.status_code == 200
    assert "T-Rex Bites" in resp.text


def test_api_requires_pin(env):
    assert env["client"].get("/api/channels").status_code == 401
    assert env["client"].post("/api/remote/up").status_code == 401


def test_login_and_default_pin_flag(env):
    c = env["client"]
    assert login(c, "0000").status_code == 401
    resp = login(c)
    assert resp.status_code == 200
    assert resp.json()["pin_is_default"] is True
    assert c.get("/api/session").json()["logged_in"] is True


def test_login_rate_limit(env):
    c = env["client"]
    for _ in range(5):
        assert login(c, "9999").status_code == 401
    assert login(c).status_code == 429


def test_change_pin_logs_out_other_devices(env):
    c = env["client"]
    login(c)
    other = TestClient(env["module"].app)
    login(other)

    assert c.post("/api/pin", json={"current_pin": "1234", "new_pin": "12"}).status_code == 400
    resp = c.post("/api/pin", json={"current_pin": "1234", "new_pin": "2468"})
    assert resp.status_code == 200
    assert resp.json()["pin_is_default"] is False

    assert c.get("/api/channels").status_code == 200
    assert other.get("/api/channels").status_code == 401
    assert login(other, "1234").status_code == 401
    assert login(other, "2468").status_code == 200


def test_channels_from_default_confs(env):
    c = env["client"]
    login(c)
    channels = c.get("/api/channels").json()["channels"]
    assert [ch["number"] for ch in channels] == [3, 5]
    trex = channels[0]
    assert {f["tag"] for f in trex["folders"]} == {"manana", "dibujos", "educativo", "peliculas"}
    assert channels[1]["folders"][0]["tag"] is None


def test_upload_lands_in_tag_folder_and_triggers_rebuild(env):
    c = env["client"]
    login(c)
    resp = c.post("/api/upload", data={"channel": "TRexTV", "tag": "dibujos"},
                  files={"file": ("Capitulo 1.mp4", b"fake-video", "video/mp4")})
    assert resp.status_code == 200, resp.text
    target = env["fs42"] / "catalog" / "trex_tv" / "dibujos" / "Capitulo 1.mp4"
    assert target.read_bytes() == b"fake-video"
    assert env["rebuilds"] == ["TRexTV"]

    # same name again gets a new name instead of overwriting
    resp = c.post("/api/upload", data={"channel": "TRexTV", "tag": "dibujos"},
                  files={"file": ("Capitulo 1.mp4", b"other", "video/mp4")})
    assert resp.json()["name"] == "Capitulo 1 (2).mp4"


def test_upload_to_loop_channel(env):
    c = env["client"]
    login(c)
    resp = c.post("/api/upload", data={"channel": "DinoLoop"},
                  files={"file": ("dino.mkv", b"x", "video/x-matroska")})
    assert resp.status_code == 200
    assert (env["fs42"] / "catalog" / "dino_loop" / "dino.mkv").exists()


@pytest.mark.parametrize("filename,expected_name", [
    ("../../etc/evil.mp4", "evil.mp4"),
    ("..\\..\\evil.mp4", "_.._evil.mp4"),
])
def test_upload_cannot_escape_folder(env, filename, expected_name):
    c = env["client"]
    login(c)
    resp = c.post("/api/upload", data={"channel": "DinoLoop"},
                  files={"file": (filename, b"x", "video/mp4")})
    assert resp.status_code == 200
    assert resp.json()["name"] == expected_name
    assert (env["fs42"] / "catalog" / "dino_loop" / expected_name).exists()


def test_upload_rejects_unknown_channel_tag_and_non_video(env):
    c = env["client"]
    login(c)
    bad_channel = c.post("/api/upload", data={"channel": "Nope", "tag": ""},
                         files={"file": ("a.mp4", b"x", "video/mp4")})
    assert bad_channel.status_code == 404
    bad_tag = c.post("/api/upload", data={"channel": "TRexTV", "tag": "../../etc"},
                     files={"file": ("a.mp4", b"x", "video/mp4")})
    assert bad_tag.status_code == 404
    not_video = c.post("/api/upload", data={"channel": "DinoLoop"},
                       files={"file": ("script.sh", b"x", "text/plain")})
    assert not_video.status_code == 400


def test_library_lists_and_deletes(env):
    c = env["client"]
    login(c)
    c.post("/api/upload", data={"channel": "DinoLoop"}, files={"file": ("a.mp4", b"x", "video/mp4")})
    lib = c.get("/api/channels").json()["channels"][1]
    assert [v["name"] for v in lib["folders"][0]["videos"]] == ["a.mp4"]

    assert c.post("/api/library/delete", json={"channel": "DinoLoop", "name": "../a.mp4"}).status_code == 404
    assert c.post("/api/library/delete", json={"channel": "DinoLoop", "name": "a.mp4"}).status_code == 200
    assert not (env["fs42"] / "catalog" / "dino_loop" / "a.mp4").exists()


def test_remote_reports_when_tv_is_offline(env):
    c = env["client"]
    login(c)
    assert c.post("/api/remote/up").status_code == 502
    assert c.post("/api/remote/explode").status_code == 400
    status = c.get("/api/status").json()
    assert status["online"] is False
