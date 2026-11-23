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


def add_bluey(c):
    ch = trex(c)
    cats = [{"tag": x["tag"], "label": x["label"]} for x in ch["categories"]]
    cats[1]["programs"] = ["Bluey", "Peppa"]
    r = c.put("/api/channels/TRexTV", json={"long_name": ch["long_name"], "number": ch["number"],
                                            "categories": cats})
    assert r.status_code == 200, r.text


def test_programs_inside_categories(env):
    c = env["client"]
    login(c)
    add_bluey(c)
    ch = trex(c)
    assert ch["categories"][1]["programs"] == [{"tag": "bluey", "label": "Bluey"}, {"tag": "peppa", "label": "Peppa"}]
    assert "dibujos/bluey" in [x["tag"] for x in ch["content"]]
    folder = env["fs42"] / "catalog" / "trex_tv" / "dibujos" / "bluey"
    assert (folder / "_bienvenida_trexbites.mp4").exists()
    # a block can use one program, in order
    week = ch["blocks"]
    week["monday"] = [{"start": 8, "end": 10, "kind": "show", "tags": ["dibujos/bluey"], "mode": "order"}]
    assert c.put("/api/channels/TRexTV/schedule", json={"blocks": week}).status_code == 200
    slot = conf_of(env)["monday"]["8"]
    assert slot["tags"] == "dibujos/bluey" and slot["sequence"] == "orden-dibujos-bluey"
    assert trex(c)["blocks"]["monday"][0]["tags"] == ["dibujos/bluey"]
    # programs that are on the schedule can't disappear
    cats = [{"tag": x["tag"], "label": x["label"], "programs": []} for x in trex(c)["categories"]]
    r = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3, "categories": cats})
    assert r.status_code == 400 and "horario" in r.json()["detail"]
    # uploading into the program removes the sample clip there and in the category
    (folder.parent / "_bienvenida_trexbites.mp4").write_bytes(b"x")
    r = c.post("/api/upload", data={"channel": "TRexTV", "tag": "dibujos/bluey"},
               files={"file": ("ep01.mp4", b"video", "video/mp4")})
    assert r.status_code == 200
    assert not (folder / "_bienvenida_trexbites.mp4").exists()
    assert not (folder.parent / "_bienvenida_trexbites.mp4").exists()


def test_hint_names_are_reserved_for_programs(env):
    c = env["client"]
    login(c)
    ch = trex(c)
    cats = [{"tag": x["tag"], "label": x["label"]} for x in ch["categories"]]
    cats[0]["programs"] = ["Monday"]
    r = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3, "categories": cats})
    assert r.status_code == 400


def test_pautas_and_fixed_videos(env):
    c = env["client"]
    login(c)
    ch = trex(c)
    r = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3,
                                            "ads": {"enabled": True, "strategy": "end", "duration": 60},
                                            "pautas": ["Juguetes"]})
    assert r.status_code == 200, r.text
    ch = trex(c)
    assert ch["pautas"] == [{"tag": "juguetes", "label": "Juguetes"}]
    tags = [f["tag"] for f in ch["folders"]]
    assert "_pauta/juguetes" in tags and "_fijos" in tags
    assert (env["fs42"] / "catalog" / "trex_tv" / "pautas" / "juguetes" / "_ident_trexbites.mp4").exists()
    week = ch["blocks"]
    week["tuesday"] = [{"start": 9, "end": 12, "kind": "show", "tags": ["dibujos"], "mode": "random",
                        "pauta": "juguetes", "start_video": "intro.mp4", "end_video": "chao.mp4"}]
    assert c.put("/api/channels/TRexTV/schedule", json={"blocks": week}).status_code == 200
    day = conf_of(env)["tuesday"]
    assert day["9"]["commercial_dir"] == "pautas/juguetes" and day["9"]["start_bump"] == "fijos/intro.mp4"
    assert "start_bump" not in day["10"] and "end_bump" not in day["10"]
    assert day["11"]["end_bump"] == "fijos/chao.mp4"
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
    r = c.post("/api/upload", data={"channel": "TRexTV", "tag": "dibujos", "when_part": "morning",
                                    "when_month": "December"},
               files={"file": ("navidad.mp4", b"video", "video/mp4")})
    assert r.status_code == 200
    assert (env["fs42"] / "catalog" / "trex_tv" / "dibujos" / "morning" / "December" / "navidad.mp4").exists()
    folder = [f for f in trex(c)["folders"] if f["tag"] == "dibujos"][0]
    video = [v for v in folder["videos"] if v["file"] == "navidad.mp4"][0]
    assert video["name"] == "morning/December/navidad.mp4" and video["when"] == "Mañana · Diciembre"
    assert c.post("/api/upload", data={"channel": "TRexTV", "tag": "dibujos", "when_part": "../x"},
                  files={"file": ("a.mp4", b"v", "video/mp4")}).status_code == 400
    r = c.post("/api/library/delete", json={"channel": "TRexTV", "tag": "dibujos", "name": video["name"]})
    assert r.status_code == 200


def test_move_video(env):
    c = env["client"]
    login(c)
    c.post("/api/upload", data={"channel": "TRexTV", "tag": "dibujos"}, files={"file": ("a.mp4", b"v", "video/mp4")})
    r = c.post("/api/library/move", json={"channel": "TRexTV", "tag": "dibujos", "name": "a.mp4",
                                          "to_channel": "TRexTV", "to_tag": "peliculas"})
    assert r.status_code == 200
    assert (env["fs42"] / "catalog" / "trex_tv" / "peliculas" / "a.mp4").exists()


def test_music_channel(env):
    c = env["client"]
    login(c)
    r = c.post("/api/channels", json={"long_name": "Rock TV", "number": 8, "type": "music"})
    assert r.status_code == 200, r.text
    conf = conf_of(env, r.json()["name"])
    assert conf["network_type"] == "standard" and conf["schedule_increment"] == 0
    assert all(str(h) in conf["monday"] for h in range(24))
    ch = [x for x in c.get("/api/channels").json()["channels"] if x["name"] == r.json()["name"]][0]
    assert ch["kind"] == "music" and ch["categories"][0]["tag"] == "videos_musicales"


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
    video = fs42 / "catalog" / "trex_tv" / "dibujos" / "ep.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"0123456789")
    (fs42 / "runtime").mkdir(exist_ok=True)
    con = sqlite3.connect(fs42 / "runtime" / "fs42_fluid.db")
    con.execute("CREATE TABLE liquid_blocks (id INTEGER PRIMARY KEY, station TEXT, liquid_type TEXT, "
                "start_time TIMESTAMP, end_time TIMESTAMP, break_strategy TEXT, title TEXT, sequence_key TEXT, "
                "break_info TEXT, content_json TEXT, plan_json TEXT)")
    now = dt.datetime.now().replace(microsecond=0)
    start = now - dt.timedelta(seconds=100)
    plan = [{"path": "catalog/trex_tv/dibujos/_none.mp4", "skip": 0, "duration": 60},
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
    assert "fijos" not in out and "/bumps" not in out
