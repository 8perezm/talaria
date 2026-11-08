"""Phase 0: GET /api/doctor diagnostics endpoint.

Covers: route registered + auth-gated, heap threshold both sides, missing
files = -1, NTP threshold, DNS/upstream failures return ok:false (not 500).
"""
import asyncio
import gc
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import config
import net
import server

ROOT = os.path.join(os.path.dirname(__file__), "..")


def _setup(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(server, "_FS_ROOT", str(tmp_path))
    monkeypatch.setattr(config, "cfgEndpoint", "")
    monkeypatch.setattr(config, "cfgAuthToken", "")
    monkeypatch.setattr(net, "apMode", False)
    server._app = None


def _get(path, headers=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        return await client.get(path, headers=headers or {})

    return asyncio.run(_do())


def test_route_registered():
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    assert '@app.get("/api/doctor")' in src


def test_auth_gated(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "cfgAuthToken", "secret123")
    server._app = None
    res = _get("/api/doctor")
    assert res.status_code == 401
    res = _get("/api/doctor", {"Authorization": "Bearer secret123"})
    assert res.status_code == 200
    body = res.json
    for k in ("heap_free", "psram_ok", "firmware_verdict", "wifi",
              "ntp_ok", "dns_ok", "dns_ms", "upstream_ok", "upstream_ms",
              "files"):
        assert k in body, "missing key: %s" % k
    server._app = None


def test_open_when_no_token(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    res = _get("/api/doctor")
    assert res.status_code == 200


def test_heap_verdict_both_sides():
    ok, v = server._doctor_verdict(8000000)
    assert ok is True and v == "SPIRAM_OCT"
    ok, v = server._doctor_verdict(90000)
    assert ok is False and v == "standard-build-suspect"
    ok, v = server._doctor_verdict(1000000)
    assert ok is False  # boundary is strictly greater-than


def test_collect_heap_threshold(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(gc, "mem_free", lambda: 8000000, raising=False)
    d = server._collect_doctor()
    assert d["heap_free"] == 8000000
    assert d["psram_ok"] is True
    assert d["firmware_verdict"] == "SPIRAM_OCT"
    monkeypatch.setattr(gc, "mem_free", lambda: 90000, raising=False)
    d = server._collect_doctor()
    assert d["psram_ok"] is False
    assert d["firmware_verdict"] == "standard-build-suspect"


def test_missing_files_are_minus_one(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    d = server._collect_doctor()
    assert set(d["files"]) == set(server._DOCTOR_FILES)
    for name, size in d["files"].items():
        assert size == -1, "%s should be -1 when missing" % name


def test_file_sizes_reported(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    payloads = {"config.json": "x" * 10, "memory.txt": "abc",
                "user.txt": "", "chatlog.jsonl": "{}\n",
                "chatlog.prev.jsonl": "y" * 100, "cron.json": "{}"}
    for name, text in payloads.items():
        with open(str(tmp_path / name), "w", encoding="utf-8") as f:
            f.write(text)
    d = server._collect_doctor()
    import os as _os
    for name in payloads:
        expect = _os.stat(str(tmp_path / name))[6]
        assert d["files"][name] == expect, name


def test_ntp_threshold(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(time, "time", lambda: 100.0)
    assert server._collect_doctor()["ntp_ok"] is False
    monkeypatch.setattr(time, "time", lambda: 800000000.0)
    assert server._collect_doctor()["ntp_ok"] is True


def test_dns_upstream_failures_not_500(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)

    def _fail(host, port, *a, **k):
        raise socket.gaierror("stubbed dns failure")

    monkeypatch.setattr(socket, "getaddrinfo", _fail)
    monkeypatch.setattr(config, "cfgEndpoint", "https://dead.invalid/")
    d = server._collect_doctor()
    assert d["dns_ok"] is False
    assert d["upstream_ok"] is False
    assert isinstance(d["dns_ms"], int) and isinstance(d["upstream_ms"], int)
    # same failure through the route must be a 200 with ok:false, not a 500
    monkeypatch.setattr(config, "cfgAuthToken", "")
    server._app = None
    try:
        res = _get("/api/doctor")
        assert res.status_code == 200
        assert res.json["dns_ok"] is False
        assert res.json["upstream_ok"] is False
    finally:
        server._app = None


def test_dns_localhost_ok(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    ok, ms = server._doctor_check_dns("localhost")
    assert ok is True
    assert isinstance(ms, int) and ms >= 0


def test_upstream_against_localhost_listener(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        port = srv.getsockname()[1]
        ok, ms = server._doctor_check_upstream("127.0.0.1", port=port)
        assert ok is True
        assert isinstance(ms, int) and ms >= 0
    finally:
        srv.close()
    # refused port -> ok:false, not an exception
    ok, _ms = server._doctor_check_upstream("127.0.0.1", port=1)
    assert ok is False


def test_upstream_no_host_never_raises():
    assert server._doctor_check_upstream("") == (False, 0)
    assert server._doctor_check_dns("") == (False, 0)


def test_doctor_json_serialisable(tmp_path, monkeypatch):
    _setup(monkeypatch, tmp_path)
    body = json.dumps(server._collect_doctor())
    assert len(body) > 50
