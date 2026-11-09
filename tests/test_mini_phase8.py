# test_mini_phase8.py — Phase 8: gateway (Telegram + unified ingress).
# No live network (gateway._tg_http seam is monkeypatched), no device.
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
import config
import cron
import gateway
import llm
import server
import sessions
from tools import registry


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.test/v1"
    config.cfgApiKey = "k"
    config.cfgModel = "m"
    config.cfgAuthToken = ""
    import net
    net.apMode = False
    monkeypatch.setattr(net, "is_connected", lambda: True)
    server._app = None
    gateway._reset_guards()
    for f in ("opt/data/tg.json",):
        try:
            os.remove(f)
        except OSError:
            pass


def _request(method, path, payload=None, raw=None, ctype=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        if method == "get":
            return await client.get(path)
        headers = {}
        body = None
        if raw is not None:
            body = raw
            headers["Content-Type"] = ctype
        elif payload is not None:
            body = json.dumps(payload)
            headers["Content-Type"] = "application/json"
        return await getattr(client, method)(path, headers=headers, body=body)

    return asyncio.run(_do())


def _write_tg(doc):
    os.makedirs("opt/data", exist_ok=True)
    with open("opt/data/tg.json", "w") as f:
        f.write(json.dumps(doc))


# ---- session key reuse ----

def test_key_format_reuse(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert sessions.session_key("telegram", 123) == "mini:telegram:123"
    assert sessions.session_key("web", "default") == "mini:web:default"
    seen = []
    gateway.allow_chat(123)
    r = gateway.handleIngress("telegram", 123, "hi",
                              run_fn=lambda t: seen.append(t) or "yo")
    assert r == "yo" and len(seen) == 1
    assert gateway._INFLIGHT == {} and gateway._GLOBAL_BUSY is False


def test_web_always_allowed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = gateway.handleIngress("web", "default", "hi", run_fn=lambda t: "web-ok")
    assert r == "web-ok"


def test_default_run_uses_empty_history_and_session_path(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import agent_core
    import sessions
    seen = []

    def _fake_run(user_msg, history=None, out=None, max_iters=None,
                  log_path=None):
        seen.append((user_msg, history, log_path))
        return "turn-ok"

    monkeypatch.setattr(agent_core, "runTurn", _fake_run)
    gateway.allow_chat(9)
    r = gateway.handleIngress("telegram", 9, "hello", run_fn=None)
    assert r == "turn-ok" and len(seen) == 1
    assert seen[0][1] == []  # empty history
    # The turn is bound to this chat's session file, not a prompt label.
    assert seen[0][0] == "hello"
    want = sessions.path_for(sessions.session_id_for("telegram", 9))
    assert seen[0][2] == want
    assert want.endswith("mini_telegram_9.jsonl")


# ---- allowlist / pairing ----

def test_unknown_chat_not_paired_and_recorded(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = gateway.handleIngress("telegram", 555, "hi",
                              run_fn=lambda t: "must not run")
    assert "not paired" in r.lower()
    c = gateway.list_chats()
    assert c["requests"] == [555] and c["allow"] == []
    assert c["configured"] is False


def test_requests_bounded_20(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for i in range(25):
        gateway.handleIngress("telegram", 1000 + i, "hi",
                              run_fn=lambda t: "nope")
    c = gateway.list_chats()
    assert len(c["requests"]) == 20
    assert c["requests"][-1] == 1024 and 1000 not in c["requests"]


def test_allow_deny_pairing_api(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert gateway.allow_chat(7)["success"] is True
    assert gateway.allow_chat("42")["success"] is True
    c = gateway.list_chats()
    assert 7 in c["allow"]
    # int/str round-trip: stored "42" matches int 42
    assert gateway.handleIngress("telegram", 42, "hi",
                                 run_fn=lambda t: "in") == "in"
    assert gateway.deny_chat(7)["success"] is True
    assert 7 not in gateway.list_chats()["allow"]
    assert "not paired" in gateway.handleIngress(
        "telegram", 7, "hi", run_fn=lambda t: "x").lower()
    assert gateway.allow_chat("")["success"] is False
    # allow clears the pairing request
    gateway.handleIngress("telegram", 77, "hi", run_fn=lambda t: "x")
    assert 77 in gateway.list_chats()["requests"]
    gateway.allow_chat(77)
    c = gateway.list_chats()
    assert 77 in c["allow"] and 77 not in c["requests"]


# ---- busy guards ----

def test_busy_second_call_receipt_and_note_next_turn(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    gateway.allow_chat(7)
    key = sessions.session_key("telegram", 7)
    ok, _ = gateway.acquire(key)
    assert ok is True
    r = gateway.handleIngress("telegram", 7, "second msg",
                              run_fn=lambda t: "must not run")
    assert "working" in r.lower()
    gateway.release(key)
    seen = []
    r2 = gateway.handleIngress("telegram", 7, "third",
                               run_fn=lambda t: seen.append(t) or "done")
    assert r2 == "done"
    assert "second msg" in seen[0]  # stashed note injected next turn


def test_guard_release_on_run_fn_raise(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    gateway.allow_chat(7)

    def _boom(t):
        raise RuntimeError("agent exploded")

    r = gateway.handleIngress("telegram", 7, "hi", run_fn=_boom)
    assert r.startswith("ERROR:")
    assert gateway._INFLIGHT == {} and gateway._GLOBAL_BUSY is False
    # next turn proceeds normally
    assert gateway.handleIngress("telegram", 7, "hi",
                                 run_fn=lambda t: "recovered") == "recovered"


def test_global_mutex_second_surface_refused(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    gateway.allow_chat(7)
    ok, _ = gateway.acquire("mini:web:default")
    assert ok is True
    r = gateway.handleIngress("telegram", 7, "hi",
                              run_fn=lambda t: "must not run")
    assert "busy" in r.lower()
    gateway.release("mini:web:default")
    assert gateway.handleIngress("telegram", 7, "hi",
                                 run_fn=lambda t: "through") == "through"


def test_acquire_kinds_and_double_release(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert gateway.acquire("mini:web:default") == (True, "")
    assert gateway.acquire("mini:web:default") == (False, "note")
    assert gateway.acquire("mini:telegram:1") == (False, "global")
    gateway.release("mini:web:default")
    gateway.release("mini:web:default")  # no-op, never raises
    assert gateway._GLOBAL_BUSY is False


# ---- Telegram transport (seam-stubbed) ----

def test_getupdates_parse_multi_update_and_bad_skipped(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = []

    def _fake_http(method, path, token, body="", timeout=15):
        calls.append((method, path))
        assert method == "GET" and "offset=100" in path and "timeout=5" in path
        doc = {"ok": True, "result": [
            {"update_id": 100,
             "message": {"chat": {"id": 7}, "text": "hi"}},
            {"update_id": 101,
             "message": {"chat": {"id": 7}}},  # non-text: consumed, skipped
            {"nope": True},  # no update_id: dropped at poll level
            {"update_id": 102,
             "channel_post": {"chat": {"id": 8}, "text": "news"}},
        ]}
        return True, json.dumps(doc), 200

    monkeypatch.setattr(gateway, "_tg_http", _fake_http)
    ok, data = gateway.tg_poll("TOK", 100)
    assert ok is True
    assert len(data["updates"]) == 3 and data["offset"] == 103
    assert len(calls) == 1


def test_poll_never_raises(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("socket exploded")

    monkeypatch.setattr(gateway, "_tg_http", _boom)
    assert gateway.tg_poll("TOK", 0)[0] is False
    assert gateway.tg_send("TOK", 7, "hi")[0] is False
    assert gateway.tg_poll("", 0) == (False, "no bot token")
    monkeypatch.setattr(gateway, "_tg_http",
                        lambda *a, **k: (True, "not json", 200))
    assert gateway.tg_poll("TOK", 0)[0] is False
    monkeypatch.setattr(gateway, "_tg_http",
                        lambda *a, **k: (True, '{"ok":false}', 200))
    assert gateway.tg_poll("TOK", 0)[0] is False
    monkeypatch.setattr(gateway, "_tg_http",
                        lambda *a, **k: (True, '{}', 500))
    assert gateway.tg_poll("TOK", 0)[0] is False


def test_send_splits_at_4000_plain_text(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    posts = []

    def _fake_http(method, path, token, body="", timeout=15):
        posts.append((method, path, token, body))
        return True, '{"ok":true}', 200

    monkeypatch.setattr(gateway, "_tg_http", _fake_http)
    ok, info = gateway.tg_send("TOK", 7, "x" * 8001)
    assert ok is True and info == {"sent": 3, "chunks": 3}
    assert len(posts) == 3
    for method, path, token, body in posts:
        assert method == "POST" and path == "/sendMessage" and token == "TOK"
        d = json.loads(body)
        assert d["chat_id"] == 7 and "parse_mode" not in d
    assert [len(json.loads(b)["text"]) for _, _, _, b in posts] == [4000, 4000, 1]
    assert gateway.tg_send("TOK", 7, "   ")[0] is False  # empty refused


# ---- tg_loop ----

def test_no_token_dormant_no_writes_no_calls(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    called = []

    def _spy(*a, **k):
        called.append(1)
        return True, "{}", 200

    monkeypatch.setattr(gateway, "_tg_http", _spy)
    r = gateway.tg_loop()
    assert r == {"success": True, "dormant": True, "processed": 0}
    assert called == [] and not os.path.exists("opt/data/tg.json")


def test_loop_processes_and_persists_offset_only_on_advance(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_tg({"bot_token": "TOK", "allow": [7], "requests": [], "offset": 100})
    doc = {"ok": True, "result": [
        {"update_id": 100, "message": {"chat": {"id": 7}, "text": "hi"}},
        {"update_id": 101, "message": {"chat": {"id": 7}}},
    ]}

    def _fake_http(method, path, token, body="", timeout=15):
        if path.startswith("/getUpdates"):
            return True, json.dumps(doc), 200
        d = json.loads(body)
        assert d["chat_id"] == 7
        return True, '{"ok":true}', 200

    monkeypatch.setattr(gateway, "_tg_http", _fake_http)
    seen = []
    monkeypatch.setattr(gateway, "handleIngress",
                        lambda p, c, t, run_fn=None: seen.append((p, c, t)) or "reply!")
    r = gateway.tg_loop()
    assert r["success"] is True and r["processed"] == 2
    assert seen == [("telegram", 7, "hi")]  # non-text consumed, not ingressed
    assert gateway.list_chats()["offset"] == 102  # persisted (advanced)


def test_loop_idle_no_rewrite(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_tg({"bot_token": "TOK", "allow": [7], "requests": [], "offset": 50})
    monkeypatch.setattr(gateway, "_tg_http",
                        lambda *a, **k: (True, '{"ok":true,"result":[]}', 200))
    before = open("opt/data/tg.json", "rb").read()
    r = gateway.tg_loop()
    assert r["success"] is True and r["processed"] == 0
    assert open("opt/data/tg.json", "rb").read() == before  # offset same: no write


def test_loop_poll_failure_never_kills(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_tg({"bot_token": "TOK", "allow": [7], "requests": [], "offset": 5})
    monkeypatch.setattr(gateway, "_tg_http",
                        lambda *a, **k: (False, "conn refused", 0))
    r = gateway.tg_loop()
    assert r["success"] is False and "refused" in r["error"]
    assert gateway.list_chats()["offset"] == 5  # untouched


def test_loop_bad_update_never_kills(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_tg({"bot_token": "TOK", "allow": [7], "requests": [], "offset": 0})
    doc = {"ok": True, "result": [
        {"update_id": 0, "message": {"chat": {"id": 7}, "text": "ok"}},
        {"update_id": 1, "message": "garbage-shape"},
    ]}
    monkeypatch.setattr(gateway, "_tg_http",
                        lambda m, p, t, b="", timeout=15:
                        (True, json.dumps(doc), 200)
                        if p.startswith("/getUpdates")
                        else (True, '{"ok":true}', 200))
    monkeypatch.setattr(gateway, "handleIngress",
                        lambda p, c, t, run_fn=None: "fine")
    r = gateway.tg_loop()
    assert r["success"] is True and r["processed"] == 2
    assert gateway.list_chats()["offset"] == 2


# ---- cron telegram wired ----

def _tg_job():
    return {"id": "j1", "prompt": "say hi", "every_s": 300, "next_run": 1,
            "enabled": True, "deliver": "telegram", "webhook_url": "",
            "skills": [], "created": 0}


def test_cron_telegram_no_token_same_envelope(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = cron.run_job(_tg_job(), lambda p: "tg reply")
    assert r["success"] is True and r["logged"] is True
    assert r["delivered"] is False and r["reason"] == "telegram-phase-8"


def test_cron_telegram_wired_to_gateway(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_tg({"bot_token": "TOK", "allow": [7], "requests": [], "offset": 0})
    sent = []
    monkeypatch.setattr(gateway, "tg_send",
                        lambda tok, cid, txt: sent.append((tok, cid, txt)) or
                        (True, {"sent": 1, "chunks": 1}))
    r = cron.run_job(_tg_job(), lambda p: "cron news")
    assert r["success"] is True and r["delivered"] is True
    assert r["target"] == "telegram" and "reason" not in r
    assert sent == [("TOK", 7, "cron news")]
    # failure path stays honest, never raises
    monkeypatch.setattr(gateway, "tg_send", lambda tok, cid, txt: (False, "boom"))
    r2 = cron.run_job(_tg_job(), lambda p: "x")
    assert r2["delivered"] is False and "boom" in r2["reason"]


# ---- /api/gateway ----

def test_api_gateway_status_and_ops(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("get", "/api/gateway")
    assert res.status_code == 200
    assert res.json["configured"] is False and res.json["allow"] == []
    assert "bot_token" not in json.dumps(res.json)  # never leaks token
    res = _request("post", "/api/gateway", {"op": "allow", "id": 11})
    assert res.status_code == 200 and res.json["ok"] is True
    assert 11 in res.json["allow"]
    res = _request("post", "/api/gateway", {"op": "allow", "allow": [12, 13]})
    assert res.status_code == 200 and 13 in res.json["allow"]  # bulk shape
    res = _request("post", "/api/gateway", {"op": "deny", "id": 12})
    assert res.status_code == 200 and 12 not in res.json["allow"]
    _write_tg({"bot_token": "x", "allow": [], "requests": [], "offset": 9})
    res = _request("post", "/api/gateway", {"op": "reset_offset"})
    assert res.status_code == 200 and res.json["offset"] == 0
    res = _request("post", "/api/gateway", {"op": "bogus"})
    assert res.status_code == 400 and res.json["success"] is False
    res = _request("post", "/api/gateway", {"op": "allow"})
    assert res.status_code == 400  # id required
    res = _request("post", "/api/gateway", {"nope": 1})
    assert res.status_code == 200  # unknown keys ignored -> status


def test_api_gateway_token_file_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("post", "/api/gateway",
                   {"op": "allow", "id": 5, "bot_token": "SECRET"})
    assert res.status_code == 200 and "note" in res.json  # ignored, flagged
    assert gateway.list_chats()["configured"] is False  # never stored
    res = _request("get", "/api/gateway")
    assert res.json["configured"] is False


def test_api_gateway_auth_gated(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config.cfgAuthToken = "secret123"
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        return await client.get("/api/gateway")

    res = asyncio.run(_do())
    assert res.status_code == 401


# ---- web busy-guard ----

def test_web_chat_busy_429_and_release(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    ok, _ = gateway.acquire("mini:web:default")
    assert ok is True
    try:
        res = _request("post", "/api/chat", {"message": "hi"})
        assert res.status_code == 429 and "busy" in res.json["error"].lower()
    finally:
        gateway.release("mini:web:default")
    monkeypatch.setattr(llm, "callLLMWithTools", lambda *a, **k: "hello back")
    res = _request("post", "/api/chat", {"message": "hi"})
    assert res.status_code == 200 and res.json["reply"] == "hello back"
    assert gateway._INFLIGHT == {} and gateway._GLOBAL_BUSY is False


# ---- repo hygiene: gitignore / blocklist / doctor / main ----

def test_gitignore_has_tg(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    base = os.path.join(os.path.dirname(__file__), "..")
    src = open(os.path.join(base, ".gitignore"), encoding="utf-8").read()
    assert "tg.json" in src.splitlines()
    assert "chatlog.jsonl" in src.splitlines()  # still present (no clobber)


def test_update_blocklist_has_tg(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    body = ("--B\r\nContent-Disposition: form-data; name=\"firmware\"; "
            "filename=\"tg.json\"\r\nContent-Type: application/octet-stream"
            "\r\n\r\n{}\r\n--B--\r\n").encode()
    res = _request("post", "/update", raw=body,
                   ctype="multipart/form-data; boundary=B")
    assert res.status_code == 400
    assert "no acceptable files" in res.json["error"]
    assert not os.path.exists(os.path.join(str(tmp_path), "opt/data/tg.json"))


def test_doctor_lists_tg_presence_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert "opt/data/tg.json" in server._DOCTOR_FILES
    d = server._collect_doctor()
    assert "opt/data/tg.json" in d["files"]  # size/-1 only, never content


def test_main_tg_poller_wiring():
    base = os.path.join(os.path.dirname(__file__), "..")
    src = open(os.path.join(base, "main.py"), encoding="utf-8").read()
    lines = src.splitlines()
    assert not any(ln.startswith("import gateway") or
                   ln.startswith("from gateway") for ln in lines)
    assert "import gateway" in src  # ...inside the loop function
    assert "create_task(_tg_poll_loop())" in src
    assert "asyncio.sleep(30)" in src
    assert "tg_loop" in src


# ---- micropython portability ----

def test_no_regex_or_bad_codecs_in_new_code():
    base = os.path.join(os.path.dirname(__file__), "..")
    for rel in (os.path.join("app", "gateway.py"), "main.py",
                os.path.join("app", "cron.py")):
        src = open(os.path.join(base, rel), encoding="utf-8").read()
        for ln in src.splitlines():
            s = ln.strip()
            assert not (s == "import re" or s.startswith("import re ") or
                        s.startswith("import re,") or
                        s.startswith("from re import")), \
                "no `re` in %s" % rel
        for codec in ("iso-8859-1", "latin-1", "cp1252", "utf-16"):
            assert codec not in src, "unsupported codec in %s" % rel
