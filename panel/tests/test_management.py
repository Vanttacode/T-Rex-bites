import datetime as dt
import json

from conftest import login

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def channels_by_name(client):
    return {c["name"]: c for c in client.get("/api/channels").json()["channels"]}


def conf_file(env, name):
    for path in (env["fs42"] / "confs").glob("*.json"):
        data = json.loads(path.read_text())
        if data.get("station_conf", {}).get("network_name") == name:
            return data["station_conf"]
    raise AssertionError(name)


def lib(env, *parts):
    return env["fs42"].joinpath("catalog", "biblioteca", *parts)


def block(start, end, tags, **extra):
    return {"start": start, "end": end, "kind": "show", "tags": tags, **extra}


def test_management_requires_pin(env):
    c = env["client"]
    assert c.post("/api/channels", json={"long_name": "X", "number": 7}).status_code == 401
    assert c.put("/api/channels/TRexTV/schedule", json={"blocks": {}}).status_code == 401
    assert c.put("/api/library", json={"categories": []}).status_code == 401
    assert c.get("/api/bedtime").status_code == 401
    assert c.post("/api/power", json={"mode": "off"}).status_code == 401
    assert c.get("/api/history").status_code == 401


def test_create_schedule_channel(env):
    c = env["client"]
    login(c)
    resp = c.post("/api/channels", json={"long_name": "Canal Películas", "number": 7, "kind": "schedule",
                                         "tags": ["peliculas"]})
    assert resp.status_code == 200, resp.text
    name = resp.json()["name"]
    assert name == "CanalPeliculas"
    ch = channels_by_name(c)[name]
    assert ch["kind"] == "schedule"
    assert ch["blocks"]["sunday"][0]["tags"] == ["peliculas"]
    conf = conf_file(env, name)
    assert conf["content_dir"] == "catalog/biblioteca"
    assert conf["bump_dir"] == "canales/canalpeliculas/bumps"
    # the channel's own folders exist before FieldStation42 sees the channel
    assert lib(env, "canales", "canalpeliculas", "bumps", "_ident_trexbites.mp4").exists()
    assert lib(env, "peliculas", "_bienvenida_trexbites.mp4").exists()
    assert env["rebuilds"] == [(name, True)]


def test_create_allday_channel_with_a_program(env):
    c = env["client"]
    login(c)
    tree = c.get("/api/channels").json()["library"]["categories"]
    tree[4]["programs"] = ["Oliver Tree"]
    assert c.put("/api/library", json={"categories": tree}).status_code == 200
    resp = c.post("/api/channels", json={"long_name": "Oliver TV", "number": 13, "kind": "allday",
                                         "tags": ["videos_musicales/oliver_tree"], "mode": "order"})
    assert resp.status_code == 200, resp.text
    ch = channels_by_name(c)["OliverTv"]
    assert ch["allday"] == {"tags": ["videos_musicales/oliver_tree"], "mode": "order"}
    conf = conf_file(env, "OliverTv")
    assert conf["schedule_increment"] == 0
    assert all(str(h) in conf["monday"] for h in range(24))
    assert conf["monday"]["0"]["sequence"] == "orden-videos_musicales-oliver_tree"
    # change what it plays
    r = c.put("/api/channels/OliverTv", json={"long_name": "Oliver TV", "number": 13,
                                              "allday": {"tags": ["videos_musicales"], "mode": "random"}})
    assert r.status_code == 200
    assert channels_by_name(c)["OliverTv"]["allday"] == {"tags": ["videos_musicales"], "mode": "random"}
    # an all-day channel has no timeline
    assert c.put("/api/channels/OliverTv/schedule", json={"blocks": {}}).status_code == 400


def test_create_channel_validation(env):
    c = env["client"]
    login(c)
    ok = {"long_name": "Nuevo", "number": 8, "kind": "schedule", "tags": ["dibujos"]}
    assert c.post("/api/channels", json={**ok, "long_name": "  "}).status_code == 400
    assert c.post("/api/channels", json={**ok, "number": 3}).status_code == 400   # taken
    assert c.post("/api/channels", json={**ok, "number": 100}).status_code == 400
    assert c.post("/api/channels", json={**ok, "kind": "music"}).status_code == 400
    assert c.post("/api/channels", json={**ok, "tags": []}).status_code == 400
    assert c.post("/api/channels", json={**ok, "tags": ["nope"]}).status_code == 400
    assert c.post("/api/channels", json={**ok, "kind": "allday", "tags": ["dibujos", "peliculas"],
                                         "mode": "order"}).status_code == 400


def test_same_name_gets_unique_id(env):
    c = env["client"]
    login(c)
    a = c.post("/api/channels", json={"long_name": "Dibus", "number": 8, "tags": ["dibujos"]}).json()["name"]
    b = c.post("/api/channels", json={"long_name": "Dibus", "number": 9, "tags": ["dibujos"]}).json()["name"]
    assert a != b
    assert conf_file(env, a)["bump_dir"] != conf_file(env, b)["bump_dir"]


def test_edit_channel_name_and_number(env):
    c = env["client"]
    login(c)
    resp = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex Kids", "number": 4})
    assert resp.status_code == 200, resp.text
    ch = channels_by_name(c)["TRexTV"]
    assert (ch["long_name"], ch["number"]) == ("T-Rex Kids", 4)
    assert env["rebuilds"] == [("TRexTV", True)]
    assert c.put("/api/channels/TRexTV", json={"long_name": "X", "number": 5}).status_code == 400


def test_edit_without_number_change_does_not_restart(env):
    c = env["client"]
    login(c)
    c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3})
    assert env["rebuilds"] == [("TRexTV", False)]


def test_delete_channel_keeps_videos(env):
    c = env["client"]
    login(c)
    c.post("/api/upload", data={"tag": "dibujos"}, files={"file": ("a.mp4", b"x", "video/mp4")})
    assert c.delete("/api/channels/DinoLoop").status_code == 200
    assert "DinoLoop" not in channels_by_name(c)
    assert lib(env, "dibujos", "a.mp4").exists()
    assert env["restarts"] == [True]
    assert c.delete("/api/channels/DinoLoop").status_code == 404


def test_save_blocks(env):
    c = env["client"]
    login(c)
    week = {day: [] for day in DAYS}
    week["saturday"] = [
        block(9, 12, ["dibujos"], mode="order", breaks="end", max_minutes=30),
        block(12, 14, ["dibujos", "peliculas"]),
        {"start": 20, "end": 23, "kind": "signoff"},
    ]
    resp = c.put("/api/channels/TRexTV/schedule", json={"blocks": week})
    assert resp.status_code == 200, resp.text

    saved = conf_file(env, "TRexTV")
    assert saved["monday"] == {}
    sat = saved["saturday"]
    assert sat["9"] == {"tags": "dibujos", "sequence": "orden-dibujos", "break_strategy": "end", "max_duration": 30}
    assert sat["11"] == {**sat["9"], "continued": True}
    assert sat["12"] == {"tags": ["dibujos", "peliculas"], "random_tags": True}
    assert sat["20"] == {"event": "signoff"} and "21" not in sat

    blocks = channels_by_name(c)["TRexTV"]["blocks"]["saturday"]
    assert [(b["start"], b["end"], b["kind"]) for b in blocks] == [(9, 12, "show"), (12, 14, "show"), (20, 21, "signoff")]
    assert blocks[0]["mode"] == "order" and blocks[0]["max_minutes"] == 30
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
    assert c.put("/api/channels/Nope/schedule", json={"blocks": {}}).status_code == 400


def test_duplicate_channel(env):
    c = env["client"]
    login(c)
    c.post("/api/channels/TRexTV/logo", files={"file": ("l.png", b"\x89PNG", "image/png")})
    resp = c.post("/api/channels/TRexTV/duplicate", json={"long_name": "T-Rex Fin de semana", "number": 4})
    assert resp.status_code == 200, resp.text
    name = resp.json()["name"]
    copy, orig = channels_by_name(c)[name], channels_by_name(c)["TRexTV"]
    assert copy["number"] == 4 and copy["long_name"] == "T-Rex Fin de semana"
    assert copy["blocks"] == orig["blocks"]
    conf = conf_file(env, name)
    assert conf["content_dir"] == "catalog/biblioteca"
    assert conf["bump_dir"] == f"canales/{name.lower()}/bumps"
    assert conf["logo_dir"] == f"canales/{name.lower()}/logos"
    assert lib(env, "canales", name.lower(), "logos", "logo.png").read_bytes() == b"\x89PNG"
    assert c.post("/api/channels/TRexTV/duplicate", json={"long_name": "X", "number": 3}).status_code == 400


def test_library_categories_and_programs(env):
    c = env["client"]
    login(c)
    tree = c.get("/api/channels").json()["library"]["categories"]
    tree[1]["label"] = "Dibujitos"
    tree[1]["programs"] = ["Bluey", "Peppa"]
    tree.append("Cuentos")
    r = c.put("/api/library", json={"categories": tree})
    assert r.status_code == 200, r.text
    data = c.get("/api/channels").json()["library"]
    cats = {x["tag"]: x for x in data["categories"]}
    assert cats["dibujos"]["label"] == "Dibujitos"
    assert [p["tag"] for p in cats["dibujos"]["programs"]] == ["bluey", "peppa"]
    assert "dibujos/bluey" in [x["tag"] for x in data["content"]]
    assert lib(env, "dibujos", "bluey", "_bienvenida_trexbites.mp4").exists()
    assert lib(env, "cuentos").is_dir()
    # reserved names (hint folders, the channels folder) are refused
    bad = data["categories"] + ["Monday"]
    assert c.put("/api/library", json={"categories": bad}).status_code == 400
    bad = data["categories"] + ["Canales"]
    assert c.put("/api/library", json={"categories": bad}).status_code == 400


def test_library_category_in_use_or_with_videos_cannot_be_removed(env):
    c = env["client"]
    login(c)
    tree = c.get("/api/channels").json()["library"]["categories"]
    without_dibujos = [x for x in tree if x["tag"] != "dibujos"]
    r = c.put("/api/library", json={"categories": without_dibujos})
    assert r.status_code == 400 and "canal" in r.json()["detail"]
    c.post("/api/upload", data={"tag": "videos_musicales"}, files={"file": ("a.mp4", b"x", "video/mp4")})
    without_music = [x for x in tree if x["tag"] != "videos_musicales"]
    r = c.put("/api/library", json={"categories": without_music})
    assert r.status_code == 400 and "videos" in r.json()["detail"]
    c.post("/api/library/delete", json={"tag": "videos_musicales", "name": "a.mp4"})
    assert c.put("/api/library", json={"categories": without_music}).status_code == 200
    assert not lib(env, "videos_musicales").exists()


def test_move_and_delete_many(env):
    c = env["client"]
    login(c)
    for n in ("a.mp4", "b.mp4", "c.mp4"):
        c.post("/api/upload", data={"tag": "dibujos"}, files={"file": (n, b"x" + n.encode(), "video/mp4")})
    tree = c.get("/api/channels").json()["library"]["categories"]
    tree[4]["programs"] = ["Oliver Tree"]
    c.put("/api/library", json={"categories": tree})
    items = [{"tag": "dibujos", "name": "a.mp4"}, {"tag": "dibujos", "name": "b.mp4"}]
    r = c.post("/api/library/move-many", json={"items": items, "to_tag": "videos_musicales/oliver_tree"})
    assert r.status_code == 200 and r.json()["moved"] == 2
    assert lib(env, "videos_musicales", "oliver_tree", "a.mp4").exists()
    assert not lib(env, "videos_musicales", "oliver_tree", "_bienvenida_trexbites.mp4").exists()
    r = c.post("/api/library/delete-many", json={"items": [{"tag": "dibujos", "name": "c.mp4"}]})
    assert r.json()["deleted"] == 1
    # the emptied category gets its sample clip back
    assert lib(env, "dibujos", "_bienvenida_trexbites.mp4").exists()
    bad = c.post("/api/library/move-many", json={"items": [{"tag": "dibujos", "name": "../x.mp4"}], "to_tag": "peliculas"})
    assert bad.status_code == 404


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
