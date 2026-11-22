import asyncio
import json

import httpx
import pytest

from trexbites_panel import fs42 as fs42_module
from trexbites_panel.fs42 import FS42Client


@pytest.fixture
def fake_fs42(tmp_path, monkeypatch):
    (tmp_path / "confs").mkdir()
    (tmp_path / "confs" / "main_config.json").write_text(json.dumps({"api_key": "secret-key-123"}))
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.headers.get("x-api-key")))
        path = request.url.path
        if request.method == "POST" and path.startswith("/build/"):
            return httpx.Response(200, json={"task_id": "t1"})
        if "/status/" in path:
            return httpx.Response(200, json={"status": "done", "log": ""})
        return httpx.Response(200, json={"ok": True})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(fs42_module.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(fs42_module, "POLL_SECONDS", 0)
    monkeypatch.setattr(fs42_module, "REBUILD_DELAY", 0)
    return FS42Client("http://fs42", tmp_path), calls


def test_remote_sends_api_key(fake_fs42):
    client, calls = fake_fs42
    asyncio.run(client.remote("channel", 3))
    asyncio.run(client.remote("volume_up"))
    assert calls == [
        ("GET", "/player/channels/3", "secret-key-123"),
        ("POST", "/player/volume/up", "secret-key-123"),
    ]


def test_rebuild_runs_catalog_then_schedule(fake_fs42):
    client, calls = fake_fs42
    asyncio.run(client.rebuild_channel("TRexTV"))
    paths = [c[1] for c in calls]
    assert paths == [
        "/build/catalog/TRexTV",
        "/build/catalog/status/t1",
        "/build/schedule/reset/TRexTV",
        "/build/schedule/reset/status/t1",
    ]
    assert client.rebuilds["TRexTV"]["status"] == "done"


def _catalog_starts(calls):
    return len([c for c in calls if c[1] == "/build/catalog/TRexTV"])


def test_changes_before_rebuild_starts_share_one_pass(fake_fs42):
    client, calls = fake_fs42

    async def scenario():
        for _ in range(3):
            client.schedule_rebuild("TRexTV")
        await client._pending["TRexTV"]

    asyncio.run(scenario())
    assert _catalog_starts(calls) == 1


def test_changes_during_rebuild_trigger_one_more_pass(fake_fs42):
    client, calls = fake_fs42

    async def scenario():
        client.schedule_rebuild("TRexTV")
        while client.rebuilds["TRexTV"]["status"] != "running":
            await asyncio.sleep(0)
        client.schedule_rebuild("TRexTV")  # a new upload lands mid-rebuild
        await client._pending["TRexTV"]

    asyncio.run(scenario())
    assert _catalog_starts(calls) == 2


def test_restart_waits_for_rebuild_and_runs_once(fake_fs42):
    client, calls = fake_fs42

    async def scenario():
        client.schedule_rebuild("TRexTV", restart=True)
        client.schedule_rebuild("DinoLoop", restart=True)
        await client._pending["TRexTV"]
        await client._pending["DinoLoop"]
        await client._restart_task

    asyncio.run(scenario())
    paths = [c[1] for c in calls]
    assert paths.count("/manage/restart") == 1
    # the restart comes after both channels were rebuilt
    assert paths[-1] == "/manage/restart"
    assert client.rebuilds["_player"]["status"] == "done"


def test_station_crud_paths(fake_fs42):
    client, calls = fake_fs42
    asyncio.run(client.create_station({"network_name": "Nuevo"}))
    asyncio.run(client.update_station("Nuevo", {"network_name": "Nuevo"}))
    asyncio.run(client.delete_station("Nuevo"))
    assert [(m, p) for m, p, _ in calls] == [
        ("POST", "/stations"), ("PUT", "/stations/Nuevo"), ("DELETE", "/stations/Nuevo"),
    ]
