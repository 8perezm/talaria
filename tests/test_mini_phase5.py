# test_mini_phase5.py — Phase 5: cron mini (<=5 jobs, 60s tick, deliver).
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
import server
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


def _write_state(jobs):
    os.makedirs("opt/data", exist_ok=True)
    with open("opt/data/cron.json", "w") as f:
        f.write(json.dumps({"jobs": jobs}))


def _job(jid="j1", prompt="say hi", every_s=3600, next_run=5000,
         enabled=True, deliver="log", skills=None, created=1000,
         webhook_url=""):
    return {"id": jid, "prompt": prompt, "every_s": every_s,
            "next_run": next_run, "enabled": enabled, "deliver": deliver,
            "webhook_url": webhook_url, "skills": skills or [],
            "created": created}


# ---- add / list / validation ----

def test_add_list_and_defaults(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = cron.add("check the plants", 300, now=10000)
    assert r["success"] is True
    j = r["job"]
    assert j["id"] == "j1" and j["every_s"] == 300
    assert j["next_run"] == 10300 and j["enabled"] is True
    assert j["deliver"] == "log" and j["skills"] == []
    l = cron.list_jobs()
    assert l["success"] and l["count"] == 1 and l["max_jobs"] == 5
    assert l["jobs"][0]["id"] == "j1"


def test_add_validation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert cron.add("", 300)["success"] is False  # prompt required
    assert cron.add("x" * 1501, 300)["success"] is False  # prompt cap
    assert cron.add("ok", "soon")["success"] is False  # every_s numeric
    assert cron.add("ok", 300, deliver="pigeon")["success"] is False
    assert cron.add("ok", 300, deliver="webhook")["success"] is False  # no url
    assert cron.add("ok", 300, deliver="webhook",
                    webhook_url="ftp://x")["success"] is False
    w = cron.add("ok", 300, deliver="webhook",
                 webhook_url="http://127.0.0.1:9/hook")
    assert w["success"] and w["job"]["webhook_url"].startswith("http://")
    t = cron.add("tg?", 300, deliver="telegram")  # accepted, stored
    assert t["success"] and t["job"]["deliver"] == "telegram"
    assert cron.add("ok", 300, skills="not-a-list-ok")["success"] is True
    assert cron.add("ok", 300, skills=[123])["success"] is False
    assert cron.add("ok", 300, skills=["a"] * 9)["success"] is False
    # missing every_s defaults (no crash)
    assert cron.add("ok")["job"]["every_s"] == 3600


def test_every_s_clamped(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert cron.add("fast", 10)["job"]["every_s"] == 60
    assert cron.add("slow", 999999)["job"]["every_s"] == 86400
    assert cron.add("neg", -5)["job"]["every_s"] == 60


def test_max_five_jobs_and_id_reuse(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    ids = []
    for i in range(5):
        r = cron.add("job %d" % i, 300)
        assert r["success"] is True
        ids.append(r["job"]["id"])
    assert ids == ["j1", "j2", "j3", "j4", "j5"]  # deterministic
    sixth = cron.add("one too many", 300)
    assert sixth["success"] is False and "5" in sixth["error"]
    assert cron.remove("j2")["success"] is True
    r = cron.add("replacement", 300)  # freed id reused, still collision-free
    assert r["success"] is True and r["job"]["id"] == "j2"


def test_pause_resume_remove_bad_id(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cron.add("pausable", 300, now=1000)
    assert cron.pause("j1")["job"]["enabled"] is False
    assert cron.resume("j1")["job"]["enabled"] is True
    for op in (cron.pause, cron.resume, cron.remove):
        r = op("nope")
        assert r["success"] is False and "nope" in r["error"]
    assert cron.remove("j1")["success"] is True
    assert cron.list_jobs()["count"] == 0
    assert cron.handle({"op": "frobnicate"})["success"] is False
    assert cron.handle({"op": "pause"})["success"] is False  # id required
    assert cron.handle("not-a-dict")["success"] is False  # never raises


# ---- tick ----

def test_tick_idle_no_write(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cron.add("idle", 3600, now=10000)  # next_run = 13600
    before = open("opt/data/cron.json", "rb").read()
    st = os.stat("opt/data/cron.json")
    r = cron.tick(11000)  # before next_run: nothing due
    assert r["due"] == [] and r["changed"] is False
    st2 = os.stat("opt/data/cron.json")
    assert st2.st_size == st.st_size
    assert open("opt/data/cron.json", "rb").read() == before
    try:
        assert st2.st_mtime_ns == st.st_mtime_ns
    except AttributeError:
        assert st2.st_mtime == st.st_mtime


def test_tick_due_updates_next_run(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_state([_job(next_run=1000, every_s=300)])
    calls = []
    r = cron.tick(5000, lambda p: calls.append(p) or "done")
    assert len(r["due"]) == 1 and r["due"][0]["id"] == "j1"
    assert r["due"][0]["next_run"] == 5300  # rescheduled from now
    assert r["changed"] is True
    assert calls == 1 * [calls[0]] and "say hi" in calls[0]
    assert len(r["results"]) == 1 and r["results"][0]["reply"] == "done"
    st = cron.list_jobs()["jobs"][0]
    assert st["next_run"] == 5300  # persisted


def test_missed_run_single_catchup(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_state([_job(next_run=100, every_s=300)])  # missed by a lot
    n = []
    r = cron.tick(99999, lambda p: n.append(p) or "caught up")
    assert len(n) == 1  # exactly once — no catch-up storm
    assert cron.list_jobs()["jobs"][0]["next_run"] == 99999 + 300


def test_disabled_skip_no_write(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_state([_job(next_run=100, enabled=False)])
    before = open("opt/data/cron.json", "rb").read()
    n = []
    r = cron.tick(99999, lambda p: n.append(p) or "must not run")
    assert r["due"] == [] and n == [] and r["changed"] is False
    assert open("opt/data/cron.json", "rb").read() == before  # stale next_run untouched


def test_run_now_keeps_schedule(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_state([_job(next_run=50000, every_s=300),
                  _job(jid="j2", next_run=100, enabled=False)])
    n = []
    r = cron.run_now("j1", lambda p: n.append(p) or "forced")
    assert r["success"] and r["reply"] == "forced"
    assert r["schedule_unchanged"] is True
    assert cron.list_jobs()["jobs"][0]["next_run"] == 50000  # untouched
    r2 = cron.run_now("j2", lambda p: "forced-paused")  # paused still forceable
    assert r2["success"] and r2["reply"] == "forced-paused"
    assert cron.run_now("nope", lambda p: "x")["success"] is False


# ---- run_job: skills prefix, log, delivery ----

def _write_skill(name="demo"):
    os.makedirs("opt/data/skills", exist_ok=True)
    with open("opt/data/skills/%s.md" % name, "w") as f:
        f.write("// desc: demo skill\n# Demo\n\nWhen to use: tests.\n\n"
                "Procedure:\n1. Test.\n\nPitfalls: none.\n\n"
                "Verification: look.\n")


def test_skills_prefix_and_missing(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_skill()
    seen = []
    r = cron.run_job(_job(skills=["demo", "ghost"]),
                     lambda p: seen.append(p) or "skilled reply")
    assert r["success"] is True
    assert "demo skill" in seen[0] and "say hi" in seen[0]
    assert r["skills_loaded"] == ["demo"] and r["skills_missing"] == ["ghost"]


def test_log_delivery_appends_once(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    before = 0
    if os.path.exists("opt/data/activity.jsonl"):
        before = sum(1 for ln in open("opt/data/activity.jsonl") if ln.strip())
    r = cron.run_job(_job(), lambda p: "logged reply")
    assert r["success"] and r["delivered"] is True and r["target"] == "log"
    after = sum(1 for ln in open("opt/data/activity.jsonl") if ln.strip())
    assert after - before == 2  # one appendChatLog: user + assistant
    # Cron output must NOT pollute a conversation session.
    assert not os.path.exists("opt/data/chatlog.jsonl")


def test_webhook_stub(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    posted = []

    def _fake_post(url, body):
        posted.append((url, body))
        return True, 200

    monkeypatch.setattr(cron, "_post", _fake_post)
    r = cron.run_job(_job(deliver="webhook",
                          webhook_url="http://127.0.0.1:9/hook"),
                     lambda p: "hook reply")
    assert r["success"] and r["delivered"] is True and r["target"] == "webhook"
    assert len(posted) == 1 and posted[0][0] == "http://127.0.0.1:9/hook"
    d = json.loads(posted[0][1])
    assert d["id"] == "j1" and d["reply"] == "hook reply"
    assert len(posted[0][1]) <= 2048  # small JSON result

    def _fail_post(url, body):
        return False, "conn refused"

    monkeypatch.setattr(cron, "_post", _fail_post)
    r2 = cron.run_job(_job(deliver="webhook",
                           webhook_url="http://127.0.0.1:9/hook"),
                      lambda p: "hook reply")
    assert r2["success"] is True  # job ran + logged...
    assert r2["delivered"] is False and "refused" in r2["reason"]  # ...delivery failed cleanly


def test_telegram_deferred(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = cron.run_job(_job(deliver="telegram"), lambda p: "tg reply")
    assert r["success"] is True and r["logged"] is True
    assert r["delivered"] is False and r["reason"] == "telegram-phase-8"


def test_run_fn_raising_never_kills_loop(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _write_state([_job(next_run=100, every_s=300),
                  _job(jid="j2", next_run=100, every_s=300)])

    def _boom(p):
        raise RuntimeError("agent exploded")

    r = cron.run_due(_boom, now=5000)  # the loop-body function, not the loop
    assert r["success"] is True and r["ran"] == 2
    assert all(x["success"] is False for x in r["results"])
    # schedules still advanced despite the crash
    assert all(j["next_run"] == 5300 for j in cron.list_jobs()["jobs"])


# ---- tool slot + dispatch ----

def test_tool_slot_and_dispatch(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    names = [t["name"] for t in agent_tools.TOOL_REGISTRY]
    assert names.index("cron") == 14  # slot 15 (1-based)
    assert names[15:18] == ["todo", "delegate_task", "exec_py"] and len(names) == 22
    assert agent_tools.all_tools_mask() == 0x3FFFFF
    s = agent_tools.execTool("cron", {"op": "add", "prompt": "via tool",
                                      "every_s": 120})
    d = json.loads(s)
    assert d["success"] is True and d["job"]["id"] == "j1"
    s2 = agent_tools.execTool("cron", {"op": "list"})
    assert json.loads(s2)["count"] == 1
    s3 = agent_tools.execTool("cron", {"op": "pause", "id": "j1"})
    assert json.loads(s3)["job"]["enabled"] is False
    s4 = agent_tools.execTool("cron", {"op": "bogus"})
    assert json.loads(s4)["success"] is False
    # run_now through the tool with a stubbed runner (no network in tests)
    monkeypatch.setattr(cron, "run_job",
                        lambda job, run_fn=None: {"success": True, "id": "j1",
                                                  "reply": "tool-run"})
    s5 = agent_tools.execTool("cron", {"op": "run_now", "id": "j1"})
    assert json.loads(s5)["reply"] == "tool-run"


# ---- HTTP API ----

def test_api_cron(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("get", "/api/cron")
    assert res.status_code == 200 and res.json["jobs"] == []
    res2 = _request("post", "/api/cron", {"op": "add", "prompt": "api job",
                                          "every_s": 120})
    assert res2.status_code == 200 and res2.json["ok"] is True
    jid = res2.json["job"]["id"]
    res3 = _request("get", "/api/cron")
    assert res3.json["count"] == 1
    assert res3.json["jobs"][0]["next_run"] > 0
    res4 = _request("post", "/api/cron", {"op": "pause", "id": jid})
    assert res4.json["ok"] is True
    res5 = _request("post", "/api/cron", {"op": "bogus"})
    assert res5.json["success"] is False
    monkeypatch.setattr(cron, "run_job",
                        lambda job, run_fn=None: {"success": True, "id": jid,
                                                  "reply": "api-run",
                                                  "logged": True,
                                                  "delivered": True,
                                                  "target": "log"})
    res6 = _request("post", "/api/cron", {"op": "run_now", "id": jid})
    assert res6.json["ok"] is True and res6.json["reply"] == "api-run"


# ---- main.py wiring ----

def test_main_cron_loop_wiring():
    src = open(os.path.join(os.path.dirname(__file__), "..", "main.py"),
               encoding="utf-8").read()
    lines = src.splitlines()
    assert not any(ln.startswith("import cron") or ln.startswith("from cron")
                   for ln in lines), "cron must be lazily imported (boot safety)"
    assert "import cron" in src  # ...inside the loop function
    assert "create_task(_cron_tick_loop())" in src
    assert "asyncio.sleep(60)" in src
    assert "run_due" in src


# ---- micropython portability ----

def test_no_regex_or_bad_codecs_in_new_code():
    base = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("cron.py", os.path.join("tools", "tool_cron.py")):
        src = open(os.path.join(base, rel), encoding="utf-8").read()
        assert "import re" not in src
        for codec in ("iso-8859-1", "latin-1", "cp1252", "utf-16"):
            assert codec not in src, "unsupported MicroPython codec in %s" % rel
