# test_api_contract.py — security and lifecycle guarantees that the dashboard
# depends on, independent of any HTML page.
#
# These were originally interleaved with assertions about the hand-written
# pages under www/. The UI is now a React SPA, so the page half of those tests
# is gone (see tests/test_spa.py) while the API half lives here: /api/reset vs
# /api/reboot semantics, backup redaction, and checkpoint pruning.
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import checkpoint  # noqa: E402
import config  # noqa: E402
import fsutil  # noqa: E402
import net  # noqa: E402
import server  # noqa: E402
from tools import registry  # noqa: E402

BASE = os.path.join(os.path.dirname(__file__), "..")

SECRETS = {
    "wifi": "WIFI-PASS-9f8e7d6c5b4a",
    "api": "sk-APIKEY-9f8e7d6c5b4a39",
    "auth": "AUTH-TOKEN-9f8e7d6c5b4a39",
    "fallback": "FALLBACK-KEY-9f8e7d6c5b",
    "bot": "998877:BOT-TOKEN-SECRET-xxyyzz",
}


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    monkeypatch.setattr(config, "cfgAuthToken", "")
    monkeypatch.setattr(config, "cfgEndpoint", "https://api.test/v1")
    monkeypatch.setattr(config, "cfgModel", "m")
    monkeypatch.setattr(net, "apMode", False)
    monkeypatch.setattr(net, "is_connected", lambda: True)
    monkeypatch.setattr(server, "_FS_ROOT", str(tmp_path))
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path))
    server._app = None


def _request(method, path, payload=None, headers=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        h = dict(headers or {})
        if method == "get":
            return await client.get(path, headers=h)
        h["Content-Type"] = "application/json"
        return await getattr(client, method)(
            path, headers=h, body=json.dumps(payload if payload is not None else {})
        )

    return asyncio.run(_do())


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _seed_secrets():
    cfg = {
        "wifi_ssid": "HomeNet",
        "wifi_pass": SECRETS["wifi"],
        "api_endpoint": "https://api.test/v1",
        "api_key": SECRETS["api"],
        "api_model": "m",
        "auth_token": SECRETS["auth"],
        "fallback_endpoint": "https://fb.test/v1",
        "fallback_key": SECRETS["fallback"],
        "fallback_model": "fb-m",
        "skills": {"write_approval": False},
    }
    with open("config.json", "w") as f:
        f.write(json.dumps(cfg))
    with open("tg.json", "w") as f:
        f.write(
            json.dumps(
                {"bot_token": SECRETS["bot"], "allow": [111], "requests": [222], "offset": 9}
            )
        )
    config.loadConfig()


# ---- lifecycle: reset wipes, reboot does not ---------------------------

def test_reset_is_factory_wipe(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        for name, body in (
            ("chatlog.jsonl", '{"r":"user","c":"hi"}\n'),
            ("memory.txt", "- test fact\n"),
            ("config.json", '{"api_model": "m"}'),
        ):
            with open(name, "w") as f:
                f.write(body)
        r = _request("post", "/api/reset", {})
        assert r.status_code == 200, r.status_code
        assert r.json.get("ok") is True and r.json.get("rebooting") is True
        for path in ("chatlog.jsonl", "memory.txt", "config.json"):
            assert not os.path.exists(path), path + " survived /api/reset"
    finally:
        server._app = None


def test_reboot_preserves_state(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        for name, body in (
            ("chatlog.jsonl", '{"r":"user","c":"hi"}\n'),
            ("memory.txt", "- test fact\n"),
            ("config.json", '{"api_model": "m"}'),
            ("cron.json", '{"jobs": []}'),
            ("tg.json", '{"bot_token": "", "allow": [], "requests": [], "offset": 0}'),
        ):
            with open(name, "w") as f:
                f.write(body)
        r = _request("post", "/api/reboot", {})
        assert r.status_code == 200, r.status_code
        assert r.json.get("ok") is True and r.json.get("rebooting") is True
        for path in ("chatlog.jsonl", "memory.txt", "config.json", "cron.json", "tg.json"):
            assert os.path.exists(path), path + " wiped by /api/reboot"
        with open("memory.txt") as f:
            assert f.read() == "- test fact\n"
    finally:
        server._app = None


def test_reboot_requires_auth(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(config, "cfgAuthToken", "secret-token-123")
        r = _request("post", "/api/reboot", {})
        assert r.status_code == 401, r.status_code
        r2 = _request("post", "/api/reboot", {}, _auth("secret-token-123"))
        assert r2.status_code == 200, r2.status_code
        assert r2.json.get("rebooting") is True
    finally:
        server._app = None


# ---- secrets never leave the device in the clear -----------------------

def test_backup_redaction_matrix(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        _seed_secrets()
        with open("memory.txt", "w") as f:
            f.write("- lobby plant watered\n")
        with open("user.txt", "w") as f:
            f.write("- likes concise replies\n")
        with open("chatlog.jsonl", "w") as f:
            f.write('{"r": "user", "c": "hello"}\n')
        with open("cron.json", "w") as f:
            f.write('{"jobs": []}')
        import skillstore

        assert skillstore.create("alpha", "// desc: alpha test skill\n# Alpha\nbody text here")[
            "success"
        ]
        r = _request("get", "/api/backup", headers=_auth(SECRETS["auth"]))
        assert r.status_code == 200, r.status_code
        body = json.dumps(r.json)
        for key, value in SECRETS.items():
            assert value not in body, "raw %s secret leaked in /api/backup" % key
        # Raw secret KEYS must not appear either — masked shapes only.
        for needle in ('"api_key":', '"wifi_pass":', '"auth_token":', '"bot_token"', '"fallback_key":'):
            assert needle not in body, needle
        assert config.maskedKey(SECRETS["api"]) in body
        assert config.maskedKey(SECRETS["fallback"]) in body
        assert r.json["gateway"]["configured"] is True
        assert r.json["gateway"]["allow"] == [111]
        for key in ("memory", "user", "chatlog_tail", "cron", "skills",
                    "bundles", "pending_counts", "config"):
            assert key in r.json, key
        assert "- lobby plant watered" in r.json["memory"]
        assert "- likes concise replies" in r.json["user"]
        assert len(r.json["chatlog_tail"]) == 1
        assert r.json["skills"] and r.json["skills"][0]["name"] == "alpha"
        assert "body text here" in r.json["skills"][0]["content"]
        assert r.json["pending_counts"] == {"memory": 0, "skills": 0}

        # ?token= download works without the header (plain links cannot set it)
        r2 = _request("get", "/api/backup?token=" + SECRETS["auth"])
        assert r2.status_code == 200, r2.status_code
        assert SECRETS["api"] not in json.dumps(r2.json)

        r3 = _request("get", "/api/backup")
        assert r3.status_code == 401, r3.status_code
    finally:
        server._app = None


# ---- checkpoint pruning ------------------------------------------------

def test_rollback_prune_keep_n(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        sizes = {}
        for i in range(1, 7):
            name = "g%d.txt.bak" % i
            with open(name, "w") as f:
                f.write("x" * (i * 100))
            sizes[name] = i * 100
        r = _request("post", "/api/rollback", {"op": "prune", "keep": 4})
        assert r.status_code == 200, (r.status_code, r.json)
        assert r.json.get("success") is True and r.json.get("ok") is True
        assert r.json["keep"] == 4 and r.json["kept"] == 4
        assert r.json["freed"] == 2
        assert r.json["freed_bytes"] == sizes["g1.txt.bak"] + sizes["g2.txt.bak"]
        assert len(r.json["pruned"]) == 2
        assert _request("get", "/api/rollback").json["count"] == 4

        bad = _request("post", "/api/rollback", {"prune": {"keep": "many"}})
        assert bad.status_code == 400, bad.status_code
        assert _request("get", "/api/rollback").json["count"] == 4

        r2 = _request("post", "/api/rollback", {"op": "prune"})
        assert r2.json["keep"] == 4 and r2.json["freed"] == 0
    finally:
        server._app = None


def test_prune_unit_default(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for i in range(5):
        with open("u%d.txt.bak" % i, "w") as f:
            f.write("y" * 10)
    res = checkpoint.prune()
    assert res["success"] is True and res["keep"] == 4
    assert res["kept"] == 4 and res["freed"] == 1
    assert checkpoint.prune("nope")["success"] is False
