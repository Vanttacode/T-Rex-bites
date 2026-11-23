import pytest
from fastapi.testclient import TestClient

from conftest import login


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


LIB = ("catalog", "biblioteca")


def test_channels_from_default_confs(env):
    c = env["client"]
    login(c)
    data = c.get("/api/channels").json()
    channels = data["channels"]
    assert [ch["number"] for ch in channels] == [3, 5]
    assert [ch["kind"] for ch in channels] == ["schedule", "allday"]
    assert {f["tag"] for f in channels[0]["folders"]} == {"_cortinillas", "_fijos"}
    assert channels[1]["allday"] == {"tags": ["dibujos"], "mode": "random"}
    assert [x["tag"] for x in data["library"]["categories"]] == ["manana", "dibujos", "educativo",
                                                                  "peliculas", "videos_musicales"]


def test_upload_lands_in_library_and_rebuilds_channels_using_it(env):
    c = env["client"]
    login(c)
    resp = c.post("/api/upload", data={"tag": "dibujos"},
                  files={"file": ("Capitulo 1.mp4", b"fake-video", "video/mp4")})
    assert resp.status_code == 200, resp.text
    target = env["fs42"].joinpath(*LIB, "dibujos", "Capitulo 1.mp4")
    assert target.read_bytes() == b"fake-video"
    # both default channels play dibujos
    assert sorted(env["rebuilds"]) == [("Dino Loop", False), ("T-Rex TV", False)]

    # same name again gets a new name instead of overwriting
    resp = c.post("/api/upload", data={"tag": "dibujos"},
                  files={"file": ("Capitulo 1.mp4", b"other", "video/mp4")})
    assert resp.json()["name"] == "Capitulo 1 (2).mp4"


@pytest.mark.parametrize("filename,expected_name", [
    ("../../etc/evil.mp4", "evil.mp4"),
    ("..\\..\\evil.mp4", "_.._evil.mp4"),
])
def test_upload_cannot_escape_folder(env, filename, expected_name):
    c = env["client"]
    login(c)
    resp = c.post("/api/upload", data={"tag": "peliculas"}, files={"file": (filename, b"x", "video/mp4")})
    assert resp.status_code == 200
    assert resp.json()["name"] == expected_name
    assert env["fs42"].joinpath(*LIB, "peliculas", expected_name).exists()


def test_upload_rejects_unknown_channel_tag_and_non_video(env):
    c = env["client"]
    login(c)
    assert c.post("/api/upload", data={"channel": "Nope", "tag": "_cortinillas"},
                  files={"file": ("a.mp4", b"x", "video/mp4")}).status_code == 404
    assert c.post("/api/upload", data={"tag": "../../etc"},
                  files={"file": ("a.mp4", b"x", "video/mp4")}).status_code == 404
    assert c.post("/api/upload", data={"tag": "canales"},
                  files={"file": ("a.mp4", b"x", "video/mp4")}).status_code == 404
    assert c.post("/api/upload", data={"tag": "dibujos"},
                  files={"file": ("script.sh", b"x", "text/plain")}).status_code == 400


def test_library_lists_and_deletes(env):
    c = env["client"]
    login(c)
    c.post("/api/upload", data={"tag": "peliculas"}, files={"file": ("a.mp4", b"x", "video/mp4")})
    lib = c.get("/api/channels").json()["library"]
    folder = [f for f in lib["folders"] if f["tag"] == "peliculas"][0]
    assert [v["name"] for v in folder["videos"]] == ["a.mp4"]
    assert c.post("/api/library/delete", json={"tag": "peliculas", "name": "../a.mp4"}).status_code == 404
    assert c.post("/api/library/delete", json={"tag": "peliculas", "name": "a.mp4"}).status_code == 200
    assert not env["fs42"].joinpath(*LIB, "peliculas", "a.mp4").exists()


def test_remote_reports_when_tv_is_offline(env):
    c = env["client"]
    login(c)
    assert c.post("/api/remote/up").status_code == 502
    assert c.post("/api/remote/explode").status_code == 400
    status = c.get("/api/status").json()
    assert status["online"] is False
