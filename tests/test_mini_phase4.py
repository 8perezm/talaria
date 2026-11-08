# test_mini_phase4.py — Phase 4: sessions (search/new/journey/trajectory).
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
import config
import memory
import server
import sessions
import skillstore as skills
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


def _skills_approval(on):
    with open("config.json", "w") as f:
        f.write(json.dumps({"skills": {"write_approval": on}}))


def _mem_approval(on):
    with open("config.json", "w") as f:
        f.write(json.dumps({"memory": {"write_approval": on}}))


def _body(desc="does things"):
    return ("// desc: %s\n# Demo Skill\n\nWhen to use: when testing.\n\n"
            "Procedure:\n1. Do the thing.\n\nPitfalls: none known.\n\n"
            "Verification: check the result.\n" % desc)


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


# ---- session keys ----

def test_session_key_format(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert sessions.session_key("web", "default") == "mini:web:default"
    assert sessions.session_key("telegram", "12345") == "mini:telegram:12345"
    # platform normalises to lowercase; separators flattened so ":" stays parseable
    assert sessions.session_key("Telegram", "abc") == "mini:telegram:abc"
    assert sessions.session_key("web", "a:b/c d") == "mini:web:a_b_c_d"
    # empty inputs fall back to web/default
    assert sessions.session_key("", "") == "mini:web:default"
    assert sessions.session_key(None, None) == "mini:web:default"


# ---- search ranking ----

def test_search_and_ranking_recency(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("the garden has basil", "noted")
    assert agent_tools.appendChatLog("basil needs water daily", "ok will water")
    r = sessions.search("basil")
    assert r["success"] is True
    assert r["count"] == 2
    # tie on hit count -> recency (later turn first)
    assert "water" in r["results"][0]["content"]
    assert "garden" in r["results"][1]["content"]
    # AND semantics: both words must occur
    r2 = sessions.search("basil water")
    assert r2["success"] is True and r2["count"] == 1
    assert "water" in r2["results"][0]["content"]


def test_search_hit_count_beats_recency(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("basil here", "ok")
    assert agent_tools.appendChatLog("basil basil basil", "ok")
    r = sessions.search("basil")
    assert r["count"] == 2
    assert r["results"][0]["content"] == "basil basil basil"
    assert r["results"][0]["score"] > r["results"][1]["score"]


def test_search_case_insensitive_and_cross_session(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("old fact about PARIS", "noted")
    sessions.new_session()
    assert agent_tools.appendChatLog("new chat about dogs", "woof")
    r = sessions.search("paris")
    assert r["success"] and r["count"] == 1
    assert r["results"][0]["source"].startswith("opt/data/sessions/")
    assert "PARIS" in r["results"][0]["content"]


def test_search_neighbors(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("q-neighbor", "a-neighbor")
    r = sessions.search("q-neighbor")
    assert r["count"] == 1
    hit = r["results"][0]
    assert hit["role"] == "user"
    assert hit["prev"] is None
    assert hit["next"] is not None and hit["next"]["content"] == "a-neighbor"
    r2 = sessions.search("a-neighbor")
    assert r2["count"] == 1
    hit2 = r2["results"][0]
    assert hit2["role"] == "assistant"
    assert hit2["prev"] is not None and hit2["prev"]["content"] == "q-neighbor"
    assert hit2["next"] is None


def test_search_caps(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for i in range(20):
        assert agent_tools.appendChatLog("capword turn %d" % i, "reply %d" % i)
    r = sessions.search("capword", limit=5)
    assert r["count"] <= 5
    assert len(json.dumps(r)) <= 2600  # ~2KB cap + query envelope
    r2 = sessions.search("capword", limit=99)
    assert r2["count"] <= 10  # clamped to SEARCH_MAX_LIMIT
    # per-hit truncation
    assert agent_tools.appendChatLog("bigcap " + "x" * 1400, "ok")
    r3 = sessions.search("bigcap")
    assert r3["count"] >= 1
    assert len(r3["results"][0]["content"]) <= 400


def test_search_missing_and_corrupt(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert not os.path.exists("opt/data/chatlog.jsonl")
    assert not os.path.exists("opt/data/chatlog.prev.jsonl")
    r = sessions.search("anything")
    assert r["success"] is True and r["count"] == 0
    os.makedirs("opt/data", exist_ok=True)
    with open("opt/data/chatlog.jsonl", "w") as f:
        f.write("not json at all\n")
        f.write('{"r": "user"}\n')  # missing content
        f.write('{"nope": 1}\n')
        f.write(json.dumps({"r": "user", "c": "valid basil turn"}) + "\n")
    r2 = sessions.search("basil")
    assert r2["success"] is True and r2["count"] == 1
    assert "valid basil turn" in r2["results"][0]["content"]
    r3 = sessions.search("")
    assert r3["success"] is False


# ---- new session (replaces the old destructive rotate) ----

def test_new_session_preserves_memories_skills_pending(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert memory.add("device", "device basil fact")["success"]
    assert memory.add("user", "user tea pref")["success"]
    _skills_approval(False)
    assert skills.create("demo", _body("demo summary"))["success"]
    _mem_approval(True)
    st = memory.add("device", "staged fact")
    assert st.get("staged")
    pr = skills.propose("draft", _body("draft summary"))
    assert pr.get("staged")
    assert agent_tools.appendChatLog("old turn", "old reply")
    old_path = agent_tools.active_log_path()
    sid = sessions.new_session()
    assert sid and sessions.active_id() == sid
    # The previous conversation is archived, NOT deleted (the old rotate()
    # removed the .prev copy every time).
    assert os.path.exists(old_path)
    assert os.path.exists("opt/data/sessions/" + sessions.active_id() + ".jsonl") is False
    assert "device basil fact" in memory.snapshot("device")
    assert "user tea pref" in memory.snapshot("user")
    assert skills.view("demo")["success"] is True
    assert len(memory.list_pending()) == 1
    assert len(skills.list_pending()) == 1
    # ...and it is still searchable from the new session.
    r = sessions.search("old turn")
    assert r["success"] and r["count"] == 1


def test_new_session_twice_keeps_both_conversations(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("first convo", "a1")
    p1 = agent_tools.active_log_path()
    sessions.new_session()
    assert agent_tools.appendChatLog("second convo", "a2")
    p2 = agent_tools.active_log_path()
    sessions.new_session()
    # Pressing New Chat again must never destroy an archived conversation.
    assert os.path.exists(p1) and os.path.exists(p2)
    titles = [s["title"] for s in sessions.list_sessions()["sessions"]]
    assert "first convo" in titles and "second convo" in titles


def test_new_session_on_empty_store(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    sid = sessions.new_session()
    assert sid
    assert sessions.active_id() == sid
    # No file until the first turn: repeated New Chat cannot litter the store.
    assert not os.path.exists("opt/data/sessions/" + sid + ".jsonl")
    assert sessions.list_sessions()["count"] == 0


def test_clear_log_api_starts_new_session(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("remember me", "sure")
    assert agent_tools.appendMemoryFact("basil")
    old_path = agent_tools.active_log_path()
    res = _request("post", "/api/memory", {"clear_log": True})
    assert res.status_code == 200
    assert res.json["cleared_log"] is True
    assert res.json["session"] == sessions.active_id()
    assert agent_tools.active_log_path() != old_path
    assert os.path.exists(old_path)  # archived, not destroyed
    r = sessions.search("remember")
    assert r["count"] == 1
    # saved memory facts stay (the clear_log guarantee)
    assert "basil" in agent_tools.readMemoryFacts()


# ---- journey ----

def test_journey_ordering_and_content(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert memory.add("device", "journey device fact")["success"]
    assert memory.add("user", "journey user fact")["success"]
    _skills_approval(False)
    assert skills.create("jskill", _body("journey skill"))["success"]
    assert agent_tools.appendChatLog("journey q", "journey a")
    chat_path = agent_tools.active_log_path()
    base = 1000000000
    os.utime("opt/data/memory.txt", (base, base))
    os.utime("opt/data/user.txt", (base + 100, base + 100))
    os.utime("opt/data/skills/jskill.md", (base + 200, base + 200))
    os.utime(chat_path, (base + 300, base + 300))
    j = sessions.journey()
    assert j["success"] is True
    evs = j["events"]
    mts = [e["mtime"] for e in evs]
    assert mts == sorted(mts)  # ascending
    kinds = set(e["kind"] for e in evs)
    assert "memory" in kinds and "skill" in kinds and "log" in kinds
    mem_ev = [e for e in evs if e.get("name") == "opt/data/memory.txt"][0]
    assert mem_ev["size"] > 0 and "%" in mem_ev["usage"]
    sk_ev = [e for e in evs if e.get("kind") == "skill"][0]
    assert sk_ev["name"] == "jskill" and sk_ev["size"] > 0
    # names in mtime order put memory.txt before the skill before the log
    # (skill events carry short name + full path — compare on path for them)
    ids = [(e.get("path") if e.get("kind") == "skill" else e.get("name")) for e in evs]
    names = [x for x in ids if x in
             ("opt/data/memory.txt", "opt/data/user.txt", "opt/data/skills/jskill.md", chat_path)]
    assert names == ["opt/data/memory.txt", "opt/data/user.txt", "opt/data/skills/jskill.md", chat_path]


def test_journey_missing_files_never_crashes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert not os.path.exists("opt/data/memory.txt")
    assert not os.path.exists("opt/data/chatlog.jsonl")
    j = sessions.journey()
    assert j["success"] is True
    assert isinstance(j["events"], list)
    # pending counts still reported as zero
    pend = [e for e in j["events"] if e.get("kind") == "pending"]
    assert len(pend) == 2
    assert all(e["count"] == 0 for e in pend)


def test_journey_api(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("jq", "ja")
    res = _request("get", "/api/journey")
    assert res.status_code == 200
    assert isinstance(res.json["events"], list)
    assert any(e["kind"] == "log" for e in res.json["events"])


# ---- trajectory ----

def test_trajectory_pairs(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("hi", "hello")
    assert agent_tools.appendChatLog("how are you", "fine")
    t = sessions.trajectory()
    assert t["pairs"] == 2 and t["truncated"] is False
    assert t["conversations"] == [
        {"from": "human", "value": "hi"},
        {"from": "gpt", "value": "hello"},
        {"from": "human", "value": "how are you"},
        {"from": "gpt", "value": "fine"},
    ]


def test_trajectory_skips_unpaired_and_spans_sessions(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    os.makedirs("opt/data/sessions", exist_ok=True)
    with open("opt/data/sessions/w1.jsonl", "w") as f:
        f.write(json.dumps({"r": "user", "c": "prev q"}) + "\n")
        f.write(json.dumps({"r": "assistant", "c": "prev a"}) + "\n")
    with open("opt/data/sessions/w2.jsonl", "w") as f:
        f.write(json.dumps({"r": "user", "c": "lonely q"}) + "\n")
        f.write(json.dumps({"r": "user", "c": "paired q"}) + "\n")
        f.write(json.dumps({"r": "assistant", "c": "paired a"}) + "\n")
    base = 1000000000
    os.utime("opt/data/sessions/w1.jsonl", (base, base))
    os.utime("opt/data/sessions/w2.jsonl", (base + 10, base + 10))
    t = sessions.trajectory()
    assert t["pairs"] == 2
    assert t["conversations"][0] == {"from": "human", "value": "prev q"}
    assert t["conversations"][2] == {"from": "human", "value": "paired q"}
    assert all("lonely" not in m["value"] for m in t["conversations"])


def test_trajectory_caps(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for i in range(60):
        assert agent_tools.appendChatLog("tq%d" % i, "ta%d" % i)
    t = sessions.trajectory()
    assert t["pairs"] == 50 and t["truncated"] is True
    assert len(t["conversations"]) == 100
    assert t["conversations"][0] == {"from": "human", "value": "tq10"}
    assert all(len(m["value"]) <= 1500 for m in t["conversations"])


def test_trajectory_api_format(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("tq", "ta")
    res = _request("get", "/api/trajectory?format=sharegpt")
    assert res.status_code == 200
    assert res.json["conversations"][0] == {"from": "human", "value": "tq"}
    res2 = _request("get", "/api/trajectory")
    assert res2.status_code == 200  # missing format defaults to sharegpt
    res3 = _request("get", "/api/trajectory?format=json")
    assert res3.status_code == 400


# ---- search API ----

def test_memory_search_api_keeps_tail(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for i in range(4):
        assert agent_tools.appendChatLog("apiq%d basil" % i, "apia%d" % i)
    res = _request("get", "/api/memory?q=basil")
    assert res.status_code == 200
    assert res.json["search"]["success"] is True
    assert res.json["search"]["count"] >= 1
    assert "log_tail" in res.json  # tail still present
    res2 = _request("get", "/api/memory?tail=2&q=basil&limit=2")
    assert res2.status_code == 200
    assert len(res2.json["log_tail"]) == 2
    assert res2.json["search"]["count"] <= 2


# ---- tool slot ----

def test_tool_slot_and_dispatch(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    names = [t["name"] for t in agent_tools.TOOL_REGISTRY]
    assert names.index("cron") == 14  # slot 15 (1-based)
    assert names[15:18] == ["todo", "delegate_task", "exec_py"] and len(names) == 22
    assert agent_tools.all_tools_mask() == 0x3FFFFF
    assert agent_tools.appendChatLog("tool basil recall", "ok")
    s = agent_tools.execTool("session_search", {"query": "basil"})
    d = json.loads(s)
    assert d["success"] is True and d["count"] >= 1
    s2 = agent_tools.execTool("session_search", {"query": ""})
    assert json.loads(s2)["success"] is False
    s3 = agent_tools.execTool("session_search", {"query": "basil", "limit": 1})
    assert json.loads(s3)["count"] <= 1


# ---- micropython portability ----

def test_no_regex_in_new_code():
    base = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("sessions.py", os.path.join("tools", "tool_session_search.py")):
        src = open(os.path.join(base, rel), encoding="utf-8").read()
        assert "import re" not in src
        assert "iso-8859-1" not in src and "latin-1" not in src
