import asyncio
import json

from conftest import login
from trexbites_panel import updates


def conf_of(env, name="trex_tv.json"):
    return json.loads((env["fs42"] / "confs" / name).read_text())["station_conf"]


def test_enable_commercials(env):
    c = env["client"]
    login(c)
    resp = c.put("/api/channels/TRexTV", json={
        "long_name": "T-Rex TV", "number": 3,
        "ads": {"enabled": True, "strategy": "end", "duration": 90},
    })
    assert resp.status_code == 200, resp.text
    conf = conf_of(env)
    assert conf["commercial_free"] is False
    assert conf["commercial_dir"] == "comerciales"
    assert (conf["break_strategy"], conf["break_duration"]) == ("end", 90)
    # commercials get their own folder with a sample clip, shown in the panel
    folder = env["fs42"] / "catalog" / "trex_tv" / "comerciales"
    assert (folder / "_ident_trexbites.mp4").exists()
    trex = [ch for ch in c.get("/api/channels").json()["channels"] if ch["name"] == "TRexTV"][0]
    assert trex["ads"] == {"enabled": True, "strategy": "end", "duration": 90}
    assert "_comerciales" in [f["tag"] for f in trex["folders"]]
    assert env["rebuilds"] == [("TRexTV", True)]

    # the first real commercial replaces the sample
    c.post("/api/upload", data={"channel": "TRexTV", "tag": "_comerciales"},
           files={"file": ("lavate-los-dientes.mp4", b"x", "video/mp4")})
    assert sorted(p.name for p in folder.iterdir()) == ["lavate-los-dientes.mp4"]


def test_commercials_validation_and_disable(env):
    c = env["client"]
    login(c)
    bad = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3,
                                              "ads": {"enabled": True, "strategy": "nunca"}})
    assert bad.status_code == 400
    bad = c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3,
                                              "ads": {"enabled": True, "duration": 5}})
    assert bad.status_code == 400
    loop = c.put("/api/channels/DinoLoop", json={"long_name": "Dino Loop", "number": 5,
                                                 "ads": {"enabled": True}})
    assert loop.status_code == 400
    c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3, "ads": {"enabled": False}})
    assert conf_of(env)["commercial_free"] is True


def test_channel_logo_upload_and_reset(env):
    c = env["client"]
    login(c)
    assert c.post("/api/channels/TRexTV/logo", files={"file": ("logo.exe", b"x", "application/x")}).status_code == 400
    resp = c.post("/api/channels/TRexTV/logo", files={"file": ("Mi Logo.PNG", b"\x89PNGfake", "image/png")})
    assert resp.status_code == 200, resp.text
    conf = conf_of(env)
    assert (conf["logo_dir"], conf["default_logo"]) == ("logos", "logo.png")
    assert (env["fs42"] / "catalog" / "trex_tv" / "logos" / "logo.png").read_bytes() == b"\x89PNGfake"
    assert c.get("/api/channels/TRexTV/logo").content == b"\x89PNGfake"
    assert env["restarts"] == [True]

    c.put("/api/channels/TRexTV", json={"long_name": "T-Rex TV", "number": 3,
                                        "logo": {"show": True, "permanent": False}})
    assert conf_of(env)["logo_permanent"] is False

    assert c.delete("/api/channels/TRexTV/logo").status_code == 200
    conf = conf_of(env)
    assert "default_logo" not in conf and "logo_dir" not in conf
    assert not (env["fs42"] / "catalog" / "trex_tv" / "logos" / "logo.png").exists()


def test_version_order():
    assert updates.is_newer("v0.3.0-beta", "0.2.0-beta")
    assert updates.is_newer("v1.0.0", "1.0.0-beta")
    assert updates.is_newer("v0.10.0", "0.9.9")
    assert not updates.is_newer("v0.2.0-beta", "0.2.0-beta")
    assert not updates.is_newer("v0.1.0", "0.2.0-beta")


def test_update_checker_needs_update_package():
    releases = [
        {"tag_name": "v0.4.0", "draft": True, "assets": [{"name": "trexbites-update-v0.4.0.tar.gz"}]},
        {"tag_name": "v0.3.0", "assets": [{"name": "trexbites-v0.3.0.iso"}]},
        {"tag_name": "v0.2.5", "name": "T-Rex Bites v0.2.5", "assets": [{"name": "trexbites-update-v0.2.5.tar.gz"}]},
    ]

    async def fetch(repo):
        return releases

    checker = updates.UpdateChecker(fetch=fetch)
    asyncio.run(checker.refresh("x/y"))
    assert checker.latest["tag"] == "v0.2.5"


def test_update_api(env):
    c = env["client"]
    login(c)

    async def fetch(repo):
        return [{"tag_name": "v0.3.0-beta", "assets": [{"name": "trexbites-update-v0.3.0-beta.tar.gz"}]}]

    env["module"].app.state.updates._fetch = fetch
    data = c.get("/api/update?check=true").json()
    assert data["current"] == "0.2.0-beta"
    assert data["available"] is True and data["latest"]["tag"] == "v0.3.0-beta"
    assert c.post("/api/update").json()["version"] == "v0.3.0-beta"
