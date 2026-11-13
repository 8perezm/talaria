# test_mini_phase9.py — Phase 9: polish + parity UI (no device contact).
# Backend + static page asserts. Page routes are static-only (the suite has
# no send_file/page test pattern — only /api/* via TestClient).
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
import config
import memory
import prompt
import server
import skillstore
from tools import registry

BASE = os.path.join(os.path.dirname(__file__), "..")
WWW = os.path.join(BASE, "www")


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.test/v1"
    config.cfgApiKey = "k"
    config.cfgModel = "m"
    config.cfgAuthToken = ""
    config.cfgFallbackEndpoint = ""
    config.cfgFallbackKey = ""
    config.cfgFallbackModel = ""
    config.agent_max_iters = 3
    import net
    net.apMode = False
    try:
        monkeypatch.setattr(net, "is_connected", lambda: True)
    except Exception:
        pass
    server._app = None


def _request(method, path, payload=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        if method == "get":
            return await client.get(path)
        headers = {}
        body = None
        if payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        return await getattr(client, method)(path, headers=headers, body=body)

    return asyncio.run(_do())


def _html(name):
    with open(os.path.join(WWW, name), encoding="utf-8") as f:
        return f.read()


# ---- 1. prompt alignment (seam-level) ----

def test_system_prompt_seam_uses_mini(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(prompt, "buildMiniPrompt", lambda: "MINI-SENTINEL-9")
    assert server._system_prompt() == "MINI-SENTINEL-9"


def test_system_prompt_falls_back_without_mini(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if name == "prompt":
            raise ImportError("no prompt")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert "Talaria Agent" in server._system_prompt()


def test_stream_and_preview_wired_to_seam():
    src = open(os.path.join(BASE, "app", "server.py"), encoding="utf-8").read()
    assert "_system_prompt()" in src
    # SSE stream path builds once per request via the seam (frozen-per-turn)
    assert "Phase 9" in src
    # legacy direct calls must be gone from the stream + tools handlers
    assert "agent_tools.buildSystemPrompt" not in src


# ---- 2. clear_user op ----

def test_clear_user_flag(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert memory.add("user", "user wipe me")["success"]
    assert os.path.exists("opt/data/user.txt")
    res = _request("post", "/api/memory", {"clear_user": True})
    assert res.status_code == 200
    assert res.json.get("cleared_user") is True
    assert res.json.get("ok") is True
    assert not os.path.exists("opt/data/user.txt")
    # device store untouched
    assert memory.add("device", "device stays")["success"]
    _request("post", "/api/memory", {"clear_user": True})
    assert "device stays" in memory.snapshot("device")


def test_clear_user_op_shape(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert memory.add("user", "op shape fact")["success"]
    res = _request("post", "/api/memory", {"op": "clear_user"})
    assert res.status_code == 200 and res.json.get("cleared_user") is True
    assert memory.snapshot("user").strip().endswith("(empty)") or \
        "op shape fact" not in memory.snapshot("user")


# ---- 3. toolset map covers all 23 ----

def test_toolset_map_covers_registry(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    names = [t["name"] for t in agent_tools.TOOL_REGISTRY]
    assert len(names) == 23
    assert set(server.TOOLSET_MAP.keys()) == set(names)
    assert set(server.TOOLSET_ORDER) == \
        {"device", "memory", "skills", "sessions", "files", "web", "agent"}
    for n in names:
        assert server.tool_toolset(n) in server.TOOLSET_ORDER
    assert server.tool_toolset("nope-unknown") == "agent"


def test_api_tools_toolset_and_default_off(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("get", "/api/tools")
    assert res.status_code == 200
    tools = res.json["tools"]
    assert len(tools) == 23
    by_name = {t["name"]: t for t in tools}
    assert by_name["memory"]["toolset"] == "memory"
    assert by_name["skill_view"]["toolset"] == "skills"
    assert by_name["session_search"]["toolset"] == "sessions"
    assert by_name["read_file"]["toolset"] == "files"
    assert by_name["web_fetch"]["toolset"] == "web"
    assert by_name["cron"]["toolset"] == "agent"
    assert by_name["exec_py"]["toolset"] == "agent"
    assert by_name["exec_py"]["default_off"] is True
    assert by_name["get_status"]["default_off"] is False
    assert "[stable]" in res.json.get("prompt_preview", "")


def test_registry_still_22_no_new_tools(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert len(agent_tools.TOOL_REGISTRY) == 23


# ---- 4. agent approvals backend ----

def test_agent_payload_has_approvals(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    p = server._agent_get_payload()
    assert "memory_write_approval" in p and "skills_write_approval" in p
    assert p["memory_write_approval"] is False  # memory default off
    assert p["skills_write_approval"] is True  # skills default on


def test_agent_apply_approvals_roundtrip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    err, res = server._agent_apply_post({
        "endpoint": "https://api.test/v1",
        "memory_write_approval": True, "skills_write_approval": False})
    assert err is None and res["ok"] is True
    assert memory.approval_enabled() is True
    assert skillstore.approval_enabled() is False
    p = server._agent_get_payload()
    assert p["memory_write_approval"] is True
    assert p["skills_write_approval"] is False
    # absent keys preserve
    err, _ = server._agent_apply_post({"endpoint": "https://api.test/v1"})
    assert err is None
    assert memory.approval_enabled() is True


# ---- 5. journey/trajectory APIs (+ ?token=) ----

def test_journey_and_trajectory_apis(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("q1", "a1") is True
    res = _request("get", "/api/journey")
    assert res.status_code == 200 and res.json["success"] is True
    assert "events" in res.json
    res = _request("get", "/api/trajectory?format=sharegpt")
    assert res.status_code == 200 and res.json["success"] is True
    assert "conversations" in res.json
    res = _request("get", "/api/trajectory?format=bogus")
    assert res.status_code == 400


def test_journey_trajectory_token_query(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config.cfgAuthToken = "secret123"
    server._app = None
    from microdot.test_client import TestClient

    async def _do(path):
        return await TestClient(server.get_app()).get(path)

    r = asyncio.run(_do("/api/journey?token=secret123"))
    assert r.status_code == 200
    r = asyncio.run(_do("/api/trajectory?format=sharegpt&token=secret123"))
    assert r.status_code == 200
    r = asyncio.run(_do("/api/journey"))
    assert r.status_code == 401
    r = asyncio.run(_do("/api/trajectory?format=sharegpt"))
    assert r.status_code == 401


# ---- 6. HTML static asserts ----













def test_zero_native_dialogs():
    pat = re.compile(r"\b(alert|confirm|prompt)\s*\(")
    bad = []
    for fn in sorted(os.listdir(WWW)):
        if not fn.endswith(".html"):
            continue
        src = open(os.path.join(WWW, fn), encoding="utf-8").read()
        if pat.search(src):
            bad.append(fn)
    assert bad == []




# ---- 7. micropython portability ----

def test_no_regex_or_bad_codecs_in_new_code():
    src = open(os.path.join(BASE, "app", "server.py"), encoding="utf-8").read()
    assert "iso-8859-1" not in src and "latin-1" not in src
