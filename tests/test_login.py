# test_login.py — POST /api/login (Hermes-style admin gate) + helper matrix.
#
# The dashboard signs in as a fixed `admin` user with the device auth token
# as the password. /api/login is a stateless verifier over the existing
# Bearer mechanism (no cookies/sessions on the MCU): the browser keeps
# sending the token as the Bearer after a successful login.
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import config  # noqa: E402
import fsutil  # noqa: E402
import net  # noqa: E402
import server  # noqa: E402
from tools import registry  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    monkeypatch.setattr(config, "cfgAuthToken", "supersecret1")
    monkeypatch.setattr(net, "apMode", False)
    monkeypatch.setattr(server, "_FS_ROOT", str(tmp_path))
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path))
    server._app = None


def _request(method, path, payload=None):
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        if method == "get":
            return await client.get(path)
        return await client.post(
            path,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload if payload is not None else {}),
        )

    return asyncio.run(_do())


def test_verify_login_matrix(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        assert server._verify_login("admin", "supersecret1") is True
        assert server._verify_login("ADMIN", "supersecret1") is True
        assert server._verify_login("  admin  ", "supersecret1") is True
        assert server._verify_login("root", "supersecret1") is False
        assert server._verify_login("", "supersecret1") is False
        assert server._verify_login("admin", "wrong") is False
        assert server._verify_login("admin", "") is False
        assert server._verify_login("admin", None) is False
    finally:
        server._app = None


def test_login_endpoint_accepts_and_rejects(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        ok = _request("post", "/api/login",
                      {"username": "admin", "password": "supersecret1"})
        assert ok.status_code == 200, (ok.status_code, ok.text)
        assert ok.json.get("ok") is True

        bad_pass = _request("post", "/api/login",
                            {"username": "admin", "password": "nope"})
        assert bad_pass.status_code == 401, bad_pass.status_code
        assert "invalid" in (bad_pass.json.get("error") or "")

        bad_user = _request("post", "/api/login",
                            {"username": "root", "password": "supersecret1"})
        assert bad_user.status_code == 401, bad_user.status_code

        missing = _request("post", "/api/login", {"username": "admin"})
        assert missing.status_code == 400, missing.status_code

        # A successful login changes nothing server-side: the same Bearer
        # keeps guarding the API (scripts and old UIs keep working).
        unauth = _request("get", "/api/stats")
        assert unauth.status_code == 401, unauth.status_code
    finally:
        server._app = None


def test_login_open_device_and_auth_shape(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        monkeypatch.setattr(config, "cfgAuthToken", "")
        open_ok = _request("post", "/api/login",
                           {"username": "admin", "password": "anything"})
        assert open_ok.status_code == 200, (open_ok.status_code, open_ok.text)

        auth = _request("get", "/api/auth")
        assert auth.status_code == 200
        assert auth.json.get("username") == "admin"
    finally:
        server._app = None
