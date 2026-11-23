"""Programs inside categories, commercial pautas, fixed videos, "when" folders,
guide channel, TV options, backup and watching on another screen."""

import datetime as dt
import io
import json
import sqlite3
import zipfile

from conftest import login

from trexbites_panel import channels, media, watch


def conf_of(env, name="TRexTV"):
    for path in (env["fs42"] / "confs").glob("*.json"):
        data = json.loads(path.read_text())
        if data.get("station_conf", {}).get("network_name") == name:
            return data["station_conf"]
    raise AssertionError(name)


def trex(c):
    return [ch for ch in c.get("/api/channels").json()["channels"] if ch["name"] == "TRexTV"][0]


def test_pautas_and_fixed_videos(env):
    c = env["client"]
    login(c)
    r = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3,
                                            "ads": {"enabled": True, "strategy": "end", "duration": 60},
                                            "pautas": ["Juguetes"]})
    assert r.status_code == 200, r.text
    ch = trex(c)
    assert ch["pautas"] == [{"tag": "juguetes", "label": "Juguetes"}]
    tags = [f["tag"] for f in ch["folders"]]
    assert "_pauta/juguetes" in tags and "_fijos" in tags and "_comerciales" in tags
    own = env["fs42"] / "catalog" / "biblioteca" / "canales" / "trextv"
    assert (own / "pautas" / "juguetes" / "_ident_trexbites.mp4").exists()
    week = ch["blocks"]
    week["tuesday"] = [{"start": 9, "end": 12, "kind": "show", "tags": ["dibujos"], "mode": "random",
                        "pauta": "juguetes", "start_video": "intro.mp4", "end_video": "chao.mp4"}]
    assert c.put("/api/channels/TRexTV/schedule", json={"blocks": week}).status_code == 200
    day = conf_of(env)["tuesday"]
    assert day["9"]["commercial_dir"] == "canales/trextv/pautas/juguetes"
    assert day["9"]["start_bump"] == "canales/trextv/fijos/intro.mp4"
    assert "start_bump" not in day["10"] and "end_bump" not in day["10"]
    assert day["11"]["end_bump"] == "canales/trextv/fijos/chao.mp4"
    block = trex(c)["blocks"]["tuesday"][0]
    assert (block["start"], block["end"], block["pauta"], block["start_video"], block["end_video"]) == \
        (9, 12, "juguetes", "intro.mp4", "chao.mp4")
    week["tuesday"][0]["pauta"] = "nope"
    assert c.put("/api/channels/TRexTV/schedule", json={"blocks": week}).status_code == 400
    week["tuesday"][0].update(pauta=None, start_video="../x.mp4")
    assert c.put("/api/channels/TRexTV/schedule", json={"blocks": week}).status_code == 400


def test_upload_with_when_folders(env):
    c = env["client"]
    login(c)
    r = c.post("/api/upload", data={"tag": "dibujos", "when_part": "morning", "when_month": "December"},
               files={"file": ("navidad.mp4", b"video", "video/mp4")})
    assert r.status_code == 200
    assert (env["fs42"] / "catalog" / "biblioteca" / "dibujos" / "morning" / "December" / "navidad.mp4").exists()
    folder = [f for f in c.get("/api/channels").json()["library"]["folders"] if f["tag"] == "dibujos"][0]
    video = [v for v in folder["videos"] if v["file"] == "navidad.mp4"][0]
    assert video["name"] == "morning/December/navidad.mp4" and video["when"] == "Mañana · Diciembre"
    assert c.post("/api/upload", data={"tag": "dibujos", "when_part": "../x"},
                  files={"file": ("a.mp4", b"v", "video/mp4")}).status_code == 400
    r = c.post("/api/library/delete", json={"tag": "dibujos", "name": video["name"]})
    assert r.status_code == 200


def test_guide_channel(env):
    c = env["client"]
    login(c)
    assert c.get("/api/guide").json()["enabled"] is False
    r = c.put("/api/guide", json={"enabled": True, "number": 3})
    assert r.status_code == 400  # 3 is T-Rex TV
    r = c.put("/api/guide", json={"enabled": True, "number": 1})
    assert r.status_code == 200 and r.json()["number"] == 1
    conf = conf_of(env, "Guia")
    assert conf["network_type"] == "guide" and conf["fullscreen"] is True and conf["play_sound"] is False
    r = c.post("/api/guide/music", files={"file": ("tema.mp3", b"mp3", "audio/mpeg")})
    assert r.status_code == 200
    assert conf_of(env, "Guia")["play_sound"] is True
    assert c.put("/api/guide", json={"enabled": False}).json()["enabled"] is False


def test_tv_settings(env):
    c = env["client"]
    login(c)
    s = c.get("/api/tv-settings").json()
    assert s["transition"] == "long" and s["convert"] is True
    r = c.put("/api/tv-settings", json={"transition": "none", "normalize": False})
    assert r.status_code == 200 and r.json()["transition"] == "none"
    env_file = env["fs42"].parent / "state" / "player.env"
    assert env_file.read_text() == "TREX_TRANSITION=none\n"
    assert c.put("/api/tv-settings", json={"transition": "boom"}).status_code == 400
    assert c.put("/api/tv-settings", json={"channel_pin": "12a4"}).status_code == 400


def test_parental_flag(env):
    c = env["client"]
    login(c)
    r = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3, "parental": True})
    assert r.status_code == 200
    assert conf_of(env)["parental_controls"] is True
    assert trex(c)["parental"] is True


def test_backup_roundtrip(env):
    c = env["client"]
    login(c)
    c.put("/api/bedtime", json={"enabled": True, "sleep_school": "20:30", "sleep_weekend": "21:30",
                                "wake_school": "07:00", "wake_weekend": "08:00"})
    data = c.get("/api/backup").content
    zf = zipfile.ZipFile(io.BytesIO(data))
    assert "manifest.json" in zf.namelist() and "channels/TRexTV.json" in zf.namelist()
    # change things, then restore
    c.put("/api/channels/TRexTV", json={"long_name": "Otro nombre", "number": 3})
    r = c.post("/api/backup", files={"file": ("r.zip", data, "application/zip")})
    assert r.status_code == 200, r.text
    assert conf_of(env)["network_long_name"] == "T-Rex TV"
    assert c.post("/api/backup", files={"file": ("x.zip", b"nope", "application/zip")}).status_code == 400
    # a backup can't point outside the media folders
    bad = io.BytesIO()
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("manifest.json", json.dumps({"format": "trexbites-backup", "version": 1}))
        z.writestr("channels/X.json", json.dumps({"station_conf": {
            "network_name": "X", "network_type": "standard", "content_dir": "/etc"}}))
    assert c.post("/api/backup", files={"file": ("b.zip", bad.getvalue(), "application/zip")}).status_code == 400


def test_watch_now_playing(env, tmp_path):
    fs42 = env["fs42"]
    video = fs42 / "catalog" / "biblioteca" / "dibujos" / "ep.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"0123456789")
    (fs42 / "runtime").mkdir(exist_ok=True)
    con = sqlite3.connect(fs42 / "runtime" / "fs42_fluid.db")
    con.execute("CREATE TABLE liquid_blocks (id INTEGER PRIMARY KEY, station TEXT, liquid_type TEXT, "
                "start_time TIMESTAMP, end_time TIMESTAMP, break_strategy TEXT, title TEXT, sequence_key TEXT, "
                "break_info TEXT, content_json TEXT, plan_json TEXT)")
    now = dt.datetime.now().replace(microsecond=0)
    start = now - dt.timedelta(seconds=100)
    plan = [{"path": "catalog/biblioteca/dibujos/_none.mp4", "skip": 0, "duration": 60},
            {"path": str(video), "skip": 5, "duration": 600}]
    con.execute("INSERT INTO liquid_blocks (station, liquid_type, start_time, end_time, break_strategy, title, "
                "content_json, plan_json) VALUES (?,?,?,?,?,?,?,?)",
                ("TRexTV", "LiquidClipBlock", str(start), str(start + dt.timedelta(minutes=30)), "end",
                 "Dinos", "[]", json.dumps(plan)))
    con.commit()
    con.close()
    playing = watch.now_playing(fs42, "TRexTV", now)
    assert playing["title"] == "Dinos" and playing["offset"] == 45.0
    c = env["client"]
    login(c)
    r = c.get("/api/watch/TRexTV").json()
    assert r["playing"]["title"] == "Dinos"
    media_resp = c.get(r["playing"]["url"], headers={"Range": "bytes=0-3"})
    assert media_resp.status_code == 206 and media_resp.content == b"0123"
    assert c.get("/api/watch/TRexTV/media?p=/etc/passwd").status_code == 404


def test_ffmpeg_command_decisions(tmp_path):
    good = {"vcodec": "h264", "acodec": "aac", "height": 720}
    assert media.ffmpeg_command(tmp_path / "a.mp4", tmp_path / "o", good, True, False) is None
    cmd = media.ffmpeg_command(tmp_path / "a.mp4", tmp_path / "o", good, True, True)
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy" and media.LOUDNORM in cmd
    heavy = {"vcodec": "hevc", "acodec": "ac3", "height": 1080}
    cmd = media.ffmpeg_command(tmp_path / "a.mkv", tmp_path / "o", heavy, True, False)
    assert "libx264" in cmd and "aac" in cmd
    assert media.ffmpeg_command(tmp_path / "a.mkv", tmp_path / "o", heavy, False, False) is not None  # ac3 audio


def test_installer_dirs_skip_optional_folders(env, capsys):
    import sys
    argv = sys.argv
    sys.argv = ["x", "--confs", str(env["fs42"] / "confs"), "--fs42", str(env["fs42"]), "--print-dirs"]
    try:
        channels.main()
    finally:
        sys.argv = argv
    out = capsys.readouterr().out
    assert "fijos" not in out and "/bumps" not in out and "biblioteca/dibujos" in out


def old_style_setup(fs42):
    """Two channels the way v0.5 stored them: their own folders and categories."""
    confs = fs42 / "confs"
    for p in confs.glob("*.json"):
        if p.name != "main_config.json":
            p.unlink()
    trex = {"network_name": "TRexTV", "network_long_name": "T-Rex TV", "channel_number": 3,
            "network_type": "standard", "content_dir": "catalog/trex_tv", "bump_dir": "bumps",
            "commercial_free": False, "commercial_dir": "comerciales", "logo_dir": "logos",
            "default_logo": "logo.png", "fallback_tag": "dibujos",
            "trexbites": {"categories": [{"tag": "dibujos", "label": "Dibujitos",
                                          "programs": [{"tag": "bluey", "label": "Bluey"}]},
                                         {"tag": "peliculas", "label": "Películas"}],
                          "pautas": [{"tag": "juguetes", "label": "Juguetes"}]},
            "monday": {"9": {"tags": "dibujos/bluey", "sequence": "orden-dibujos-bluey",
                             "commercial_dir": "pautas/juguetes", "start_bump": "fijos/intro.mp4"},
                       "10": {"tags": "peliculas"}}}
    loop = {"network_name": "DinoLoop", "network_long_name": "Oliver TV", "channel_number": 5,
            "network_type": "loop", "content_dir": "catalog/dino_loop"}
    # a third channel that had its own "dibujos"
    other = {"network_name": "Otro", "network_long_name": "Otro", "channel_number": 7,
             "network_type": "standard", "content_dir": "catalog/otro", "bump_dir": "bumps",
             "monday": {"8": {"tags": "dibujos"}}}
    for name, conf in (("trex_tv", trex), ("dino_loop", loop), ("otro", other)):
        (confs / f"{name}.json").write_text(json.dumps({"station_conf": conf}))
    files = {
        "trex_tv/dibujos/ep1.mp4": b"1", "trex_tv/dibujos/bluey/b1.mp4": b"b",
        "trex_tv/dibujos/_bienvenida_trexbites.mp4": b"s", "trex_tv/peliculas/p.mp4": b"p",
        "trex_tv/comerciales/ad.mp4": b"a", "trex_tv/pautas/juguetes/toy.mp4": b"t",
        "trex_tv/bumps/_ident_trexbites.mp4": b"i", "trex_tv/fijos/intro.mp4": b"f",
        "trex_tv/logos/logo.png": b"L",
        "dino_loop/song1.mp4": b"s1", "dino_loop/song2.mkv": b"s2",
        "otro/dibujos/x.mp4": b"x", "otro/bumps/_ident_trexbites.mp4": b"i",
    }
    for rel, data in files.items():
        path = fs42 / "catalog" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def test_migration_moves_everything_into_the_library(env):
    from trexbites_panel import migrate
    fs42 = env["fs42"]
    old_style_setup(fs42)
    assert migrate.migrate(fs42 / "confs", fs42) == 3
    lib = fs42 / "catalog" / "biblioteca"
    assert (lib / "dibujos" / "ep1.mp4").read_bytes() == b"1"
    assert (lib / "dibujos" / "bluey" / "b1.mp4").exists()
    assert not (lib / "dibujos" / "_bienvenida_trexbites.mp4").exists()  # real videos there
    assert (lib / "canales" / "trextv" / "comerciales" / "ad.mp4").exists()
    assert (lib / "canales" / "trextv" / "pautas" / "juguetes" / "toy.mp4").exists()
    assert (lib / "canales" / "trextv" / "fijos" / "intro.mp4").exists()
    assert (lib / "canales" / "trextv" / "logos" / "logo.png").exists()
    # the loop channel's songs became a category named after it
    assert (lib / "oliver_tv" / "song1.mp4").exists() and (lib / "oliver_tv" / "song2.mkv").exists()
    # the second "dibujos" got its own category
    assert (lib / "dibujos_otro" / "x.mp4").exists()
    assert not (fs42 / "catalog" / "trex_tv").exists() and not (fs42 / "catalog" / "dino_loop").exists()
    trex = json.loads((fs42 / "confs" / "trex_tv.json").read_text())["station_conf"]
    assert trex["content_dir"] == "catalog/biblioteca"
    assert trex["commercial_dir"] == "canales/trextv/comerciales"
    assert trex["logo_dir"] == "canales/trextv/logos"
    assert trex["monday"]["9"] == {"tags": "dibujos/bluey", "sequence": "orden-dibujos-bluey",
                                   "commercial_dir": "canales/trextv/pautas/juguetes",
                                   "start_bump": "canales/trextv/fijos/intro.mp4"}
    other = json.loads((fs42 / "confs" / "otro.json").read_text())["station_conf"]
    assert other["monday"]["8"]["tags"] == "dibujos_otro"
    assert (fs42 / "confs" / "respaldo-antes-de-biblioteca" / "trex_tv.json").exists()
    # it reads well in the panel
    c = env["client"]
    login(c)
    data = c.get("/api/channels").json()
    by = {ch["name"]: ch for ch in data["channels"]}
    assert by["DinoLoop"]["kind"] == "allday" and by["DinoLoop"]["allday"]["tags"] == ["oliver_tv"]
    assert by["TRexTV"]["blocks"]["monday"][0]["pauta"] == "juguetes"
    assert by["TRexTV"]["blocks"]["monday"][0]["start_video"] == "intro.mp4"
    cats = {x["tag"]: x for x in data["library"]["categories"]}
    assert cats["dibujos"]["label"] == "Dibujitos" and cats["oliver_tv"]["label"] == "Oliver TV"
    assert [p["tag"] for p in cats["dibujos"]["programs"]] == ["bluey"]
    # running it again changes nothing
    assert migrate.migrate(fs42 / "confs", fs42) == 0
