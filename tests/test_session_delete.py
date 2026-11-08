# test_session_delete.py — sessions are conversations, not turns.
#
# Storage is one file per conversation under opt/data/sessions/. The Sessions
# page lists those files (GET /api/sessions), resumes one by activating it,
# and deletes one whole conversation (POST /api/sessions/delete). The old
# per-turn delete machinery is gone: ids are session ids, so a stale turn id
# (chatlog.jsonl:0:1:abcdef) can never address a file.
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools  # noqa: E402
import config  # noqa: E402
import net  # noqa: E402
import server  # noqa: E402
import sessions  # noqa: E402
from tools import registry  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    monkeypatch.setattr(config, "cfgEndpoint", "https://api.test/v1")
    monkeypatch.setattr(config, "cfgApiKey", "k")
    monkeypatch.setattr(config, "cfgModel", "m")
    monkeypatch.setattr(config, "cfgAuthToken", "")
    monkeypatch.setattr(net, "apMode", False)
    monkeypatch.setattr(net, "is_connected", lambda: True)
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


def _append_raw(role, content, path):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps({"r": role, "c": content}) + "\n")


def _write_session(sid, pairs):
    path = "opt/data/sessions/" + sid + ".jsonl"
    os.makedirs("opt/data/sessions", exist_ok=True)
    with open(path, "a") as f:
        for u, a in pairs:
            f.write(json.dumps({"r": "user", "c": u}) + "\n")
            f.write(json.dumps({"r": "assistant", "c": a}) + "\n")
    return path


# ---- store shape ----

def test_list_sessions_lists_conversations_not_turns(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("first question", "first answer")
    p1 = agent_tools.active_log_path()
    sessions.new_session()
    assert agent_tools.appendChatLog("second question", "second answer")
    p2 = agent_tools.active_log_path()
    res = sessions.list_sessions()
    assert res["success"] is True and res["count"] == 2
    titles = [s["title"] for s in res["sessions"]]
    assert titles == ["second question", "first question"]  # newest first
    for row in res["sessions"]:
        assert row["id"] in (sessions.safe_id(sessions._stem(os.path.basename(p1))),
                             sessions.safe_id(sessions._stem(os.path.basename(p2))))
        assert row["bytes"] > 0
        assert row["kind"] == "web"
    assert res["sessions"][0]["active"] is True
    assert res["sessions"][1]["active"] is False


def test_session_isolation_tail_and_turns(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    a = sessions.new_session()
    assert agent_tools.appendChatLog("in A", "reply A")
    b = sessions.new_session()
    assert agent_tools.appendChatLog("in B", "reply B")
    ra = sessions.read_turns(a)
    rb = sessions.read_turns(b)
    assert [t["human"] for t in ra["turns"]] == ["in A"]
    assert [t["human"] for t in rb["turns"]] == ["in B"]
    # The active session is B; A's content must not leak into it.
    assert "in A" not in open(sessions.path_for(b)).read()


def test_turns_pairing_and_pending_tail(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.new_session()
    _write_session(sid, [("q0", "a0"), ("q1", "a1")])
    _append_raw("user", "unanswered", sessions.path_for(sid))
    r = sessions.read_turns(sid)
    assert [t["human"] for t in r["turns"]] == ["q0", "q1", "unanswered"]
    assert r["turns"][-1]["agent"] == ""
    assert [t["index"] for t in r["turns"]] == [1, 2, 3]
    assert r["truncated"] is False


def test_turns_cap_keeps_newest(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.new_session()
    for i in range(60):
        assert agent_tools.appendChatLog("q%d" % i, "a%d" % i)
    r = sessions.read_turns(sessions.active_id())
    assert r["count"] == 50 and r["truncated"] is True
    assert r["turns"][0]["human"] == "q10"
    assert r["turns"][-1]["human"] == "q59"


# ---- activate ----

def test_set_active_roundtrip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.new_session()
    assert agent_tools.appendChatLog("hello", "hi")
    other = sessions.new_session()
    assert sessions.active_id() == other
    assert sessions.set_active(sid) == sid
    assert sessions.active_id() == sid
    assert agent_tools.active_log_path() == sessions.path_for(sid)


def test_active_never_returns_a_foreign_path(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert sessions.set_active("../../etc/passwd") == ""
    assert sessions.path_for("..") == ""
    assert sessions.path_for("chatlog.jsonl:0:1:abc") == ""
    assert sessions.active_id()  # falls back to a real session


# ---- delete ----

def test_delete_session_removes_only_that_file(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    a = sessions.new_session()
    assert agent_tools.appendChatLog("keep me", "ok")
    pa = sessions.path_for(a)
    b = sessions.new_session()
    assert agent_tools.appendChatLog("delete me", "bye")
    pb = sessions.path_for(b)
    res = sessions.delete_session(b)
    assert res["success"] is True
    assert res["was_active"] is True and res["active"]
    assert os.path.exists(pa) and not os.path.exists(pb)
    assert sessions.active_id() == res["active"]
    assert [s["title"] for s in sessions.list_sessions()["sessions"]] == ["keep me"]


def test_delete_active_starts_a_new_conversation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    a = sessions.new_session()
    assert agent_tools.appendChatLog("old", "x")
    res = sessions.delete_session(a)
    assert res["success"] is True
    assert res["active"] and res["active"] != a
    assert sessions.active_id() == res["active"]


def test_delete_refuses_bad_ids(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for bad in ("", "nope/../x", "chatlog.jsonl:0:1:0", "mini:telegram:1",
                "x.jsonl", ".", "..", "a" * 60):
        r = sessions.delete_session(bad)
        assert r["success"] is False
        assert "invalid session id" in r["error"]


def test_delete_missing_session(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = sessions.delete_session("w111")
    assert r["success"] is False and "not found" in r["error"]


# ---- legacy migration ----

def test_legacy_logs_migrate_into_sessions(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs("opt/data", exist_ok=True)
    _append_raw("user", "ancient question", "opt/data/chatlog.prev.jsonl")
    _append_raw("assistant", "ancient answer", "opt/data/chatlog.prev.jsonl")
    _append_raw("user", "current question", "opt/data/chatlog.jsonl")
    _append_raw("assistant", "current answer", "opt/data/chatlog.jsonl")
    base = 1000000000
    os.utime("opt/data/chatlog.prev.jsonl", (base, base))
    os.utime("opt/data/chatlog.jsonl", (base + 100, base + 100))
    sid = sessions.ensure_store()
    assert not os.path.exists("opt/data/chatlog.jsonl")
    assert not os.path.exists("opt/data/chatlog.prev.jsonl")
    titles = [s["title"] for s in sessions.list_sessions()["sessions"]]
    assert "current question" in titles and "ancient question" in titles
    # The newer conversation becomes active.
    assert sessions.read_turns(sid)["turns"][0]["human"] == "current question"


def test_migration_is_idempotent(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs("opt/data", exist_ok=True)
    _append_raw("user", "once", "opt/data/chatlog.jsonl")
    first = sessions.ensure_store()
    second = sessions.ensure_store()
    assert first == second
    assert sessions.list_sessions()["count"] == 1


# ---- API ----

def test_sessions_api_roundtrip(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("api session", "reply")
    res = _request("get", "/api/sessions")
    assert res.status_code == 200
    body = res.json
    assert body["count"] == 1
    assert body["sessions"][0]["title"] == "api session"
    sid = body["sessions"][0]["id"]

    # New conversation
    created = _request("post", "/api/sessions", {})
    assert created.status_code == 200
    new_sid = created.json["session"]
    assert new_sid and new_sid != sid
    assert sessions.active_id() == new_sid

    # Activate the old one
    act = _request("post", "/api/sessions/activate", {"id": sid})
    assert act.status_code == 200 and act.json["session"] == sid
    assert sessions.active_id() == sid

    # Its tail comes back through /api/memory
    mem = _request("get", "/api/memory?session=" + sid)
    assert mem.status_code == 200
    assert mem.json["session"] == sid
    assert mem.json["log_tail"][0] == {"role": "user", "content": "api session"}

    # Delete it
    gone = _request("post", "/api/sessions/delete", {"id": sid})
    assert gone.status_code == 200
    assert gone.json["deleted"] == sid
    assert _request("get", "/api/sessions").json["count"] == 0


def test_memory_defaults_to_active_and_activates_on_request(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    a = sessions.new_session()
    assert agent_tools.appendChatLog("A only", "ok")
    b = sessions.new_session()
    assert agent_tools.appendChatLog("B only", "ok")
    r = _request("get", "/api/memory")
    assert r.json["session"] == b
    assert [e["content"] for e in r.json["log_tail"]] == ["B only", "ok"]
    # Reading with ?session=...&activate=1 re-points the web UI.
    r2 = _request("get", "/api/memory?session=" + a + "&activate=1")
    assert r2.json["session"] == a
    assert sessions.active_id() == a


def test_sessions_delete_requires_auth(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "cfgAuthToken", "secret123")
    assert agent_tools.appendChatLog("q", "a")
    sid = sessions.active_id()
    assert _request("get", "/api/sessions").status_code == 401
    assert _request("post", "/api/sessions/delete", {"id": sid}).status_code == 401
    assert _request("post", "/api/sessions", {}).status_code == 401
    ok = _request("get", "/api/sessions?token=secret123")
    assert ok.status_code == 200
    # Deleting with the token works (same pattern as journey/trajectory).
    assert _request("post", "/api/sessions/delete", {"id": sid}).status_code == 401
    assert sessions.list_sessions()["count"] == 1


# ---- telegram ----

def test_telegram_session_id_is_stable_and_sanitised(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.session_id_for("telegram", 12345)
    assert sid == "mini_telegram_12345"
    assert sessions.session_id_for("telegram", 12345) == sid
    assert sessions.safe_id(sid) == sid
    p = sessions.path_for(sid)
    assert p == "opt/data/sessions/mini_telegram_12345.jsonl"
    # Telegram sessions never become the web active pointer.
    web = sessions.active_id()
    assert web != sid
