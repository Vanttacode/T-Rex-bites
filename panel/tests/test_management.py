import datetime as dt
import json

from conftest import login


def channels_by_name(client):
    return {c["name"]: c for c in client.get("/api/channels").json()["channels"]}


def test_management_requires_pin(env):
    c = env["client"]
    assert c.post("/api/channels", json={"long_name": "X", "number": 7}).status_code == 401
    assert c.put("/api/channels/TRexTV/schedule", json={"week": {}}).status_code == 401
    assert c.get("/api/bedtime").status_code == 401
    assert c.post("/api/power", json={"mode": "off"}).status_code == 401
    assert c.get("/api/history").status_code == 401


def test_channels_expose_categories_and_schedule(env):
    c = env["client"]
    login(c)
    trex = channels_by_name(c)["TRexTV"]
    assert [cat["label"] for cat in trex["categories"]] == ["Mañana", "Dibujos animados", "Educativos", "Películas"]
    assert trex["schedule"]["monday"]["7"] == "manana"
    assert trex["schedule"]["monday"]["20"] == "signoff"
    assert "3" not in trex["schedule"]["monday"]
    assert channels_by_name(c)["DinoLoop"]["schedule"] is None


def test_create_scheduled_channel(env):
    c = env["client"]
    login(c)
    resp = c.post("/api/channels", json={
        "long_name": "Canal Películas", "number": 7, "type": "standard",
        "categories": ["Películas", "Música infantil"],
    })
    assert resp.status_code == 200, resp.text
    name = resp.json()["name"]
    assert name == "CanalPeliculas"

    ch = channels_by_name(c)[name]
    assert ch["long_name"] == "Canal Películas"
    assert [cat["tag"] for cat in ch["categories"]] == ["peliculas", "musica_infantil"]
    assert ch["schedule"]["sunday"]["7"] == "peliculas"
    # empty category folders get the sample clip so the TV always has something to show
    folder = env["fs42"] / "catalog" / "canalpeliculas" / "musica_infantil"
    assert (folder / "_bienvenida_trexbites.mp4").exists()
    # new channels need the player restarted
    assert env["rebuilds"] == [(name, True)]


def test_create_loop_channel(env):
    c = env["client"]
    login(c)
    resp = c.post("/api/channels", json={"long_name": "Música", "number": 8, "type": "loop"})
    assert resp.status_code == 200
    ch = channels_by_name(c)["Musica"]
    assert ch["type"] == "loop"
    assert ch["folders"][0]["tag"] is None


def test_create_channel_validation(env):
    c = env["client"]
    login(c)
    taken = c.post("/api/channels", json={"long_name": "Otro", "number": 3, "categories": ["A"]})
    assert taken.status_code == 400
    assert "T-Rex TV" in taken.json()["detail"]
    assert c.post("/api/channels", json={"long_name": "", "number": 9, "categories": ["A"]}).status_code == 400
    assert c.post("/api/channels", json={"long_name": "X", "number": 100, "categories": ["A"]}).status_code == 400
    assert c.post("/api/channels", json={"long_name": "X", "number": 9, "categories": []}).status_code == 400
    assert c.post("/api/channels", json={"long_name": "X", "number": 9, "categories": ["A", "a"]}).status_code == 400
    assert c.post("/api/channels", json={"long_name": "X", "number": 9, "type": "web"}).status_code == 400
    assert env["stations"].calls == []


def test_same_name_gets_unique_id(env):
    c = env["client"]
    login(c)
    first = c.post("/api/channels", json={"long_name": "Dino Loop", "number": 9, "type": "loop"})
    assert first.json()["name"] == "DinoLoop2"


def test_edit_channel_name_number_and_categories(env):
    c = env["client"]
    login(c)
    resp = c.put("/api/channels/TRexTV", json={
        "long_name": "T-Rex Kids", "number": 4,
        "categories": [{"tag": "manana", "label": "Mañana"}, {"tag": "dibujos", "label": "Dibujitos"},
                       {"tag": "educativo", "label": "Educativos"}, {"tag": "peliculas", "label": "Películas"},
                       "Cuentos"],
    })
    assert resp.status_code == 200, resp.text
    ch = channels_by_name(c)["TRexTV"]
    assert (ch["long_name"], ch["number"]) == ("T-Rex Kids", 4)
    assert ch["categories"][-1] == {"tag": "cuentos", "label": "Cuentos"}
    # renaming a category keeps its tag (and its videos); new categories get a folder
    assert ch["categories"][1] == {"tag": "dibujos", "label": "Dibujitos"}
    assert (env["fs42"] / "catalog" / "trex_tv" / "cuentos" / "_bienvenida_trexbites.mp4").exists()
    assert env["rebuilds"] == [("TRexTV", True)]


def test_category_in_schedule_cannot_be_removed(env):
    c = env["client"]
    login(c)
    resp = c.put("/api/channels/TRexTV", json={
        "long_name": "T-Rex TV", "number": 3, "categories": [{"tag": "manana", "label": "Mañana"}, {"tag": "dibujos", "label": "Dibujos"},
                                                       {"tag": "peliculas", "label": "Películas"}],
    })
    assert resp.status_code == 400
    assert "Educativos" in resp.json()["detail"]


def test_edit_without_number_change_does_not_restart(env):
    c = env["client"]
    login(c)
    c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3})
    assert env["rebuilds"] == [("TRexTV", False)]


def test_delete_channel_keeps_videos(env):
    c = env["client"]
    login(c)
    c.post("/api/upload", data={"channel": "DinoLoop"}, files={"file": ("a.mp4", b"x", "video/mp4")})
    assert c.delete("/api/channels/DinoLoop").status_code == 200
    assert "DinoLoop" not in channels_by_name(c)
    assert (env["fs42"] / "catalog" / "dino_loop" / "a.mp4").exists()
    assert env["restarts"] == [True]
    assert c.delete("/api/channels/DinoLoop").status_code == 404


def test_save_schedule(env):
    c = env["client"]
    login(c)
    week = {day: {} for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}
    week["saturday"] = {"9": "peliculas", "10": "peliculas", "12": "signoff"}
    resp = c.put("/api/channels/TRexTV/schedule", json={"week": week})
    assert resp.status_code == 200, resp.text

    saved = json.loads((env["fs42"] / "confs" / "trex_tv.json").read_text())["station_conf"]
    assert saved["monday"] == {}
    assert saved["saturday"] == {"9": {"tags": "peliculas"}, "10": {"tags": "peliculas"}, "12": {"event": "signoff"}}
    # categories survive even when the schedule no longer uses them
    assert [cat["tag"] for cat in channels_by_name(c)["TRexTV"]["categories"]] == \
        ["manana", "dibujos", "educativo", "peliculas"]
    assert env["rebuilds"] == [("TRexTV", False)]


def test_schedule_validation(env):
    c = env["client"]
    login(c)
    bad_tag = c.put("/api/channels/TRexTV/schedule", json={"week": {"monday": {"9": "nope"}}})
    assert bad_tag.status_code == 400
    bad_hour = c.put("/api/channels/TRexTV/schedule", json={"week": {"monday": {"24": "dibujos"}}})
    assert bad_hour.status_code == 400
    loop = c.put("/api/channels/DinoLoop/schedule", json={"week": {}})
    assert loop.status_code == 400
    assert c.put("/api/channels/Nope/schedule", json={"week": {}}).status_code == 400


def test_upload_replaces_sample_clip_and_delete_restores_it(env):
    c = env["client"]
    login(c)
    c.post("/api/channels", json={"long_name": "Cuentos", "number": 9, "type": "loop"})
    folder = env["fs42"] / "catalog" / "cuentos"
    assert (folder / "_bienvenida_trexbites.mp4").exists()

    c.post("/api/upload", data={"channel": "Cuentos"}, files={"file": ("uno.mp4", b"x", "video/mp4")})
    assert sorted(p.name for p in folder.iterdir()) == ["uno.mp4"]

    c.post("/api/library/delete", json={"channel": "Cuentos", "name": "uno.mp4"})
    assert sorted(p.name for p in folder.iterdir()) == ["_bienvenida_trexbites.mp4"]


def test_bedtime_settings_roundtrip(env):
    c = env["client"]
    login(c)
    data = c.get("/api/bedtime").json()
    assert data["settings"]["enabled"] is False
    assert data["power"]["state"] == "on"

    resp = c.put("/api/bedtime", json={**data["settings"], "enabled": True, "sleep_school": "19:45"})
    assert resp.status_code == 200
    assert c.get("/api/bedtime").json()["settings"]["sleep_school"] == "19:45"
    assert c.put("/api/bedtime", json={**data["settings"], "sleep_school": "25:00"}).status_code == 400


def test_power_override(env):
    c = env["client"]
    login(c)
    off = c.post("/api/power", json={"mode": "off"}).json()["power"]
    assert (off["state"], off["reason"]) == ("off", "manual")
    assert c.get("/api/status").json()["power"]["state"] == "off"
    auto = c.post("/api/power", json={"mode": "auto"}).json()["power"]
    assert auto["state"] == "on"
    assert c.post("/api/power", json={"mode": "explode"}).status_code == 400


def test_history_endpoint(env):
    c = env["client"]
    login(c)
    history = env["module"].app.state.history
    now = dt.datetime.now()
    for _ in range(3):
        history.record_minute(now, {"status": "playing", "network_name": "TRexTV", "channel_number": 3, "title": "Dinos"})
    days = c.get("/api/history?days=3").json()["days"]
    assert len(days) == 3
    assert days[0]["total_minutes"] == 3
    assert days[0]["programs"][0] == {"channel": 3, "network": "TRexTV", "title": "Dinos",
                                      "minutes": 3, "channel_name": "T-Rex TV"}
