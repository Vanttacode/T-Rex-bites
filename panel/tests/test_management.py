import datetime as dt
import json

from conftest import login


def channels_by_name(client):
    return {c["name"]: c for c in client.get("/api/channels").json()["channels"]}


def test_management_requires_pin(env):
    c = env["client"]
    assert c.post("/api/channels", json={"long_name": "X", "number": 7}).status_code == 401
    assert c.put("/api/channels/TRexTV/schedule", json={"blocks": {}}).status_code == 401
    assert c.get("/api/bedtime").status_code == 401
    assert c.post("/api/power", json={"mode": "off"}).status_code == 401
    assert c.get("/api/history").status_code == 401


def test_channels_expose_categories_and_schedule(env):
    c = env["client"]
    login(c)
    trex = channels_by_name(c)["TRexTV"]
    assert [cat["label"] for cat in trex["categories"]] == ["Mañana", "Dibujos animados", "Educativos", "Películas"]
    monday = trex["blocks"]["monday"]
    assert (monday[0]["start"], monday[0]["end"], monday[0]["tags"]) == (7, 10, ["manana"])
    assert monday[-1] == {"start": 20, "end": 21, "kind": "signoff"}
    assert channels_by_name(c)["DinoLoop"]["blocks"] is None


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
    assert ch["blocks"]["sunday"][0] == {"start": 7, "end": 20, "kind": "show", "tags": ["peliculas"],
                                        "mode": "random", "breaks": None,
                                        "min_minutes": None, "max_minutes": None,
                                        "pauta": None, "start_video": None, "end_video": None}
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
    assert ch["categories"][-1] == {"tag": "cuentos", "label": "Cuentos", "programs": []}
    # renaming a category keeps its tag (and its videos); new categories get a folder
    assert ch["categories"][1] == {"tag": "dibujos", "label": "Dibujitos", "programs": []}
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


def block(start, end, tags, **extra):
    return {"start": start, "end": end, "kind": "show", "tags": tags, **extra}


def test_save_blocks(env):
    c = env["client"]
    login(c)
    week = {day: [] for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")}
    week["saturday"] = [
        block(9, 12, ["dibujos"], mode="order", breaks="end", max_minutes=30),
        block(12, 14, ["dibujos", "peliculas"]),
        {"start": 20, "end": 23, "kind": "signoff"},
    ]
    resp = c.put("/api/channels/TRexTV/schedule", json={"blocks": week})
    assert resp.status_code == 200, resp.text

    saved = json.loads((env["fs42"] / "confs" / "trex_tv.json").read_text())["station_conf"]
    assert saved["monday"] == {}
    sat = saved["saturday"]
    assert sat["9"] == {"tags": "dibujos", "sequence": "orden-dibujos", "break_strategy": "end", "max_duration": 30}
    assert sat["11"] == {**sat["9"], "continued": True}
    assert sat["12"] == {"tags": ["dibujos", "peliculas"], "random_tags": True}
    assert sat["20"] == {"event": "signoff"} and "21" not in sat

    # read back as the same blocks
    blocks = channels_by_name(c)["TRexTV"]["blocks"]["saturday"]
    assert [(b["start"], b["end"], b["kind"]) for b in blocks] == [(9, 12, "show"), (12, 14, "show"), (20, 21, "signoff")]
    assert blocks[0]["mode"] == "order" and blocks[0]["max_minutes"] == 30
    # categories survive even when the schedule no longer uses them
    assert [cat["tag"] for cat in channels_by_name(c)["TRexTV"]["categories"]] == \
        ["manana", "dibujos", "educativo", "peliculas"]
    assert env["rebuilds"] == [("TRexTV", False)]


def test_block_validation(env):
    c = env["client"]
    login(c)

    def put(blocks):
        return c.put("/api/channels/TRexTV/schedule", json={"blocks": {"monday": blocks}})

    assert put([block(9, 10, ["nope"])]).status_code == 400
    assert put([block(23, 25, ["dibujos"])]).status_code == 400
    assert put([block(9, 12, ["dibujos"]), block(11, 13, ["peliculas"])]).status_code == 400  # overlap
    assert put([block(9, 10, ["dibujos", "peliculas"], mode="order")]).status_code == 400
    assert put([block(9, 10, ["dibujos"], breaks="nunca")]).status_code == 400
    assert put([block(9, 10, ["dibujos"], min_minutes=40, max_minutes=20)]).status_code == 400
    assert put([block(9, 10, [])]).status_code == 400
    assert c.put("/api/channels/DinoLoop/schedule", json={"blocks": {}}).status_code == 400
    assert c.put("/api/channels/Nope/schedule", json={"blocks": {}}).status_code == 400


def test_duplicate_channel(env):
    c = env["client"]
    login(c)
    resp = c.post("/api/channels/TRexTV/duplicate", json={"long_name": "T-Rex Fin de semana", "number": 4})
    assert resp.status_code == 200, resp.text
    copy = channels_by_name(c)[resp.json()["name"]]
    orig = channels_by_name(c)["TRexTV"]
    assert copy["number"] == 4 and copy["long_name"] == "T-Rex Fin de semana"
    assert copy["blocks"] == orig["blocks"] and copy["categories"] == orig["categories"]
    # same videos by default
    conf = json.loads((env["fs42"] / "confs" / f"{resp.json()['name']}.json").read_text())["station_conf"]
    assert conf["content_dir"] == "catalog/trex_tv"
    assert env["rebuilds"][-1] == (resp.json()["name"], True)

    own = c.post("/api/channels/TRexTV/duplicate", json={"long_name": "Otro", "number": 6, "share_videos": False})
    conf = json.loads((env["fs42"] / "confs" / f"{own.json()['name']}.json").read_text())["station_conf"]
    assert conf["content_dir"] == "catalog/otro"
    assert (env["fs42"] / "catalog" / "otro" / "dibujos" / "_bienvenida_trexbites.mp4").exists()
    taken = c.post("/api/channels/TRexTV/duplicate", json={"long_name": "X", "number": 3})
    assert taken.status_code == 400


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


def test_scheduled_channels_get_a_bump_folder(env):
    """FieldStation42 fills gaps between programs from bump_dir; without it schedules fail."""
    c = env["client"]
    login(c)
    c.post("/api/channels", json={"long_name": "Cuentos", "number": 9, "categories": ["Cuentos"]})
    conf = json.loads((env["fs42"] / "confs" / "Cuentos.json").read_text())["station_conf"]
    assert conf["bump_dir"] == "bumps"
    assert (env["fs42"] / "catalog" / "cuentos" / "bumps" / "_ident_trexbites.mp4").exists()
    # cortinillas (bumps) and fixed videos are their own upload folders, not categories
    assert [f["tag"] for f in channels_by_name(c)["Cuentos"]["folders"]] == ["cuentos", "_cortinillas", "_fijos"]
    assert [cat["tag"] for cat in channels_by_name(c)["Cuentos"]["categories"]] == ["cuentos"]
    assert c.post("/api/channels", json={"long_name": "X", "number": 10, "categories": ["Bumps"]}).status_code == 400


def test_old_channel_without_bump_dir_is_repaired_on_save(env):
    c = env["client"]
    login(c)
    path = env["fs42"] / "confs" / "trex_tv.json"
    data = json.loads(path.read_text())
    del data["station_conf"]["bump_dir"]
    path.write_text(json.dumps(data))
    c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3})
    assert json.loads(path.read_text())["station_conf"]["bump_dir"] == "bumps"
    assert (env["fs42"] / "catalog" / "trex_tv" / "bumps" / "_ident_trexbites.mp4").exists()
