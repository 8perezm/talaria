# test_sessions_export.py — per-conversation export (Sessions page row button).
#
# One Sessions row = one file under opt/data/sessions. The row's download button
# hits GET /api/sessions/export?id=<sid>, which streams the WHOLE conversation
# (not the /api/memory tail) as an attachment. The old page-level Export button
# only ever dumped the active conversation's last N turns, so it is gone.
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import config  # noqa: E402
import net  # noqa: E402
import server  # noqa: E402
import sessions  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(config, "cfgEndpoint", "https://api.test/v1")
    monkeypatch.setattr(config, "cfgApiKey", "k")
    monkeypatch.setattr(config, "cfgModel", "m")
    monkeypatch.setattr(config, "cfgAuthToken", "")
    monkeypatch.setattr(net, "apMode", False)
    monkeypatch.setattr(net, "is_connected", lambda: True)
    server._app = None


def _request(path, headers=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        return await client.get(path, headers=dict(headers or {}))

    return asyncio.run(_do())


def _write_session(sid, pairs):
    path = "opt/data/sessions/" + sid + ".jsonl"
    os.makedirs("opt/data/sessions", exist_ok=True)
    with open(path, "a") as f:
        for u, a in pairs:
            f.write(json.dumps({"r": "user", "c": u}) + "\n")
            f.write(json.dumps({"r": "assistant", "c": a}) + "\n")
    return path


# ---- transcript builder ----


def test_export_text_keeps_the_whole_message(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.new_session()
    # Longer than TRAJ_VALUE_CAP (1500) — trajectory() truncates, export must not.
    long_answer = "answer-" + ("x" * 2400)
    _write_session(sid, [("what is my heap", long_answer)])
    res = sessions.export_text(sid)
    assert res["success"] is True
    assert res["id"] == sid and res["messages"] == 2
    assert res["truncated"] is False
    assert ("USER: what is my heap") in res["text"]
    assert ("AGENT: " + long_answer) in res["text"]
    # Header carries the id and the title (first user line).
    assert res["text"].startswith("talaria agent — conversation " + sid)
    assert "Title: what is my heap" in res["text"]


def test_export_text_refuses_bad_and_missing_ids(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for bad in ("", "..", "x/y", "chatlog.jsonl:0:1:abc", "a" * 60):
        res = sessions.export_text(bad)
        assert res["success"] is False
        assert "invalid session id" in res["error"]
    missing = sessions.export_text("w111")
    assert missing["success"] is False and "not found" in missing["error"]


def test_export_text_caps_a_huge_log(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(sessions, "EXPORT_MAX_CHARS", 300)
    sid = sessions.new_session()
    _write_session(sid, [("q%d" % i, "a" * 80) for i in range(20)])
    res = sessions.export_text(sid)
    assert res["success"] is True
    assert res["truncated"] is True
    assert "export truncated" in res["text"]
    assert len(res["text"]) < 2000


def test_export_text_tolerates_corrupt_lines(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.new_session()
    path = "opt/data/sessions/" + sid + ".jsonl"
    os.makedirs("opt/data/sessions", exist_ok=True)
    with open(path, "w") as f:
        f.write("not json\n")
        f.write(json.dumps({"r": "user", "c": "kept"}) + "\n")
        f.write(json.dumps({"r": "system", "c": "dropped"}) + "\n")
        f.write(json.dumps({"r": "assistant", "c": "reply"}) + "\n")
    res = sessions.export_text(sid)
    assert res["success"] is True and res["messages"] == 2
    assert "dropped" not in res["text"]


# ---- API ----


def test_export_endpoint_returns_an_attachment(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.new_session()
    _write_session(sid, [("api question", "api answer")])
    res = _request("/api/sessions/export?id=" + sid)
    assert res.status_code == 200
    assert res.headers.get("Content-Type", "").startswith("text/plain")
    disp = res.headers.get("Content-Disposition", "")
    assert "attachment" in disp and ("talaria-%s.txt" % sid) in disp
    assert "USER: api question" in res.text
    assert "AGENT: api answer" in res.text


def test_export_endpoint_rejects_unknown_ids(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for bad in ("", "..", "x/y"):
        assert _request("/api/sessions/export?id=" + bad).status_code == 404
    assert _request("/api/sessions/export?id=w999").status_code == 404


def test_export_endpoint_requires_auth_or_token(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "cfgAuthToken", "secret123")
    sid = sessions.new_session()
    _write_session(sid, [("secret q", "secret a")])
    assert _request("/api/sessions/export?id=" + sid).status_code == 401
    ok = _request("/api/sessions/export?id=%s&token=secret123" % sid)
    assert ok.status_code == 200
    assert "USER: secret q" in ok.text


def test_export_does_not_touch_the_active_pointer(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    a = sessions.new_session()
    _write_session(a, [("older", "x")])
    b = sessions.new_session()
    _write_session(b, [("newer", "y")])
    assert sessions.active_id() == b
    assert sessions.export_text(a)["success"] is True
    assert sessions.active_id() == b
