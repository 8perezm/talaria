# test_dash3.py — D3 (stats counters + /keys page + doctor gc.collect fix).
# No device contact. Static asserts + TestClient route checks.
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
import config
import server

BASE = os.path.join(os.path.dirname(__file__), "..")
WWW = os.path.join(BASE, "www")


def _read(name):
    with open(os.path.join(WWW, name), encoding="utf-8") as f:
        return f.read()


def _nav_of(page_src):
    m = re.search(r'<nav class="side" data-shell>.*?</nav>', page_src, re.S)
    assert m, "no shell <nav> block found"
    return m.group(0)


def _canonical_nav():
    css = _read("dash.css")
    return css.split("/*NAV-START\n", 1)[1].split("\nNAV-END*/", 1)[0]


# ---- 1. size cap ----



# ---- 2. nav parity (admin + sessions + logs + keys identical) ----



# ---- 3. zero native dialogs in shell pages ----



# ---- 4. node --check inline scripts ----

def _inline_scripts(src):
    out = []
    idx = 0
    while True:
        s = src.find("<script", idx)
        if s < 0:
            break
        gt = src.find(">", s)
        e = src.find("</script>", gt)
        assert e >= 0, "unterminated <script> block"
        if "src=" not in src[s:gt + 1] and src[gt + 1:e].strip():
            out.append(src[gt + 1:e])
        idx = e + 9
    return out




# ---- 5. doctor heap fix: gc.collect() before mem_free() ----

def test_doctor_heap_collect_before_free(monkeypatch):
    calls = []

    class _FakeGC(object):
        def collect(self):
            calls.append("collect")

        def mem_free(self):
            calls.append("mem_free")
            return 8000000

    monkeypatch.setitem(sys.modules, "gc", _FakeGC())
    assert server._doctor_heap_free() == 8000000
    assert calls == ["collect", "mem_free"], calls


def test_doctor_heap_host_guard(monkeypatch):
    # Host CPython gc has no mem_free -> 0, exactly as before the fix.
    class _HostLikeGC(object):
        def collect(self):
            pass

    monkeypatch.setitem(sys.modules, "gc", _HostLikeGC())
    assert server._doctor_heap_free() == 0


# ---- 6. stats counters: shape + reset-on-boot semantics ----

def test_stats_counters_shape():
    s = server._collect_stats(False)
    for k in ("turns_since_boot", "tool_calls",
              "last_chat_ms", "last_upstream_ms"):
        assert k in s, "missing key: %s" % k
    assert isinstance(s["turns_since_boot"], int)
    assert isinstance(s["tool_calls"], dict)
    assert isinstance(s["last_chat_ms"], int)
    assert s["last_upstream_ms"] is None or \
        isinstance(s["last_upstream_ms"], int)
    json.dumps(s)  # must stay JSON-serialisable (null, not None-str)


def test_stats_counters_reset_on_boot_semantics():
    # Counters are plain RAM module state: a reboot (fresh import) resets
    # them. Reset to boot values here and assert the API reports zeros/null.
    server._STATS_TURNS_SINCE_BOOT = 0
    server._STATS_LAST_CHAT_MS = 0
    server._STATS_LAST_UPSTREAM_MS = None
    agent_tools._TOOL_CALL_COUNTS.clear()
    s = server._collect_stats(False)
    assert s["turns_since_boot"] == 0
    assert s["tool_calls"] == {}
    assert s["last_chat_ms"] == 0
    assert s["last_upstream_ms"] is None
    src = open(os.path.join(BASE, "app", "server.py"), encoding="utf-8").read()
    assert "reset on" in src.lower() and "boot" in src.lower()


def test_tool_calls_increment_at_choke_point():
    agent_tools._TOOL_CALL_COUNTS.clear()
    out = agent_tools.execTool("zz_no_tool_d3", {})
    assert "unknown tool" in out  # loop contract unchanged
    s = server._collect_stats(False)
    assert s["tool_calls"].get("zz_no_tool_d3") == 1
    agent_tools.execTool("zz_no_tool_d3", {})
    assert server._collect_stats(False)["tool_calls"]["zz_no_tool_d3"] == 2
    # _collect_stats returns a copy: mutating it must not corrupt the counter.
    s["tool_calls"]["zz_no_tool_d3"] = 999
    assert server._collect_stats(False)["tool_calls"]["zz_no_tool_d3"] == 2
    agent_tools._TOOL_CALL_COUNTS.clear()


# ---- 7. routes + serving + link audit ----

def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    os.mkdir("www")
    for n in ("admin.html", "sessions.html", "logs.html", "keys.html",
              "dash.css", "icons.svg"):
        shutil.copy(os.path.join(WWW, n), os.path.join("www", n))
    import net
    monkeypatch.setattr(config, "cfgAuthToken", "")
    monkeypatch.setattr(config, "cfgEndpoint", "https://api.test/v1")
    monkeypatch.setattr(config, "cfgModel", "m")
    monkeypatch.setattr(net, "apMode", False)
    monkeypatch.setattr(net, "is_connected", lambda: True)
    server._STATS_TURNS_SINCE_BOOT = 0
    server._STATS_LAST_CHAT_MS = 0
    server._STATS_LAST_UPSTREAM_MS = None
    agent_tools._TOOL_CALL_COUNTS.clear()
    try:
        import gateway as _gw
        _gw._reset_guards()
    except Exception:
        pass
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
            path, headers=h,
            body=json.dumps(payload if payload is not None else {}))

    return asyncio.run(_do())


def _ctype(res):
    h = getattr(res, "headers", {}) or {}
    for k, v in (h.items() if hasattr(h, "items") else []):
        if str(k).lower() == "content-type":
            return str(v)
    return ""












# ---- 8. keys markers + no dead links ----





# ---- 9. redaction matrix: raw secrets in NO GET body after API-set values ----

