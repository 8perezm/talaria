# test_config_api.py — the schema-driven Config page API.
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
    config.cfgSsid = ""
    config.cfgPass = ""
    config.cfgEndpoint = ""
    config.cfgApiKey = ""
    config.cfgModel = "gpt-4o-mini"
    config.cfgAuthToken = ""
    config.cfgFallbackEndpoint = ""
    config.cfgFallbackKey = ""
    config.cfgFallbackModel = ""
    config.cfgMdnsName = config.MDNS_NAME
    config.cfgApSsid = config.AP_SSID
    config.agent_max_iters = 3
    config.cfgChatEntryChars = config.DEFAULT_CHAT_ENTRY_CHARS
    config.cfgChatLogMaxKB = config.DEFAULT_CHAT_LOG_MAX_KB
    config.cfgChatLogKeepKB = config.DEFAULT_CHAT_LOG_KEEP_KB
    config.cfgChatRestoreTurns = config.DEFAULT_CHAT_RESTORE_TURNS
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    monkeypatch.setattr(net, "apMode", False)
    monkeypatch.setattr(net, "is_connected", lambda: True)
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
            body=json.dumps(payload or {}),
        )

    return asyncio.run(_do())


def test_config_form_get_and_save(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        r = _request("get", "/api/config/form")
        assert r.status_code == 200, r.json
        assert r.json["path"] == "config.yaml"
        fields = {f["key"]: f for f in r.json["fields"]}
        assert "agent.endpoint" in fields
        assert fields["agent.api_key"]["type"] == "secret"
        assert fields["security.auth_token"]["type"] == "readonly"
        r = _request("post", "/api/config/form", {"values": {
            "agent.endpoint": "https://api.test/v1",
            "agent.model": "m",
            "agent.api_key": "sk-1234567890",
            "chat.restore_turns": 12,
        }})
        assert r.status_code == 200, r.json
        assert r.json["ok"] is True and r.json["restart_required"] is False
        assert config.cfgEndpoint == "https://api.test/v1"
        assert config.cfgApiKey == "sk-1234567890"
        assert config.cfgChatRestoreTurns == 12
        text = open("config.yaml").read()
        assert "api_key: sk-1234567890" in text
        assert "restore_turns: 12" in text
        # A blank secret keeps the stored key.
        r = _request("post", "/api/config/form", {"values": {
            "agent.model": "m2", "agent.api_key": ""}})
        assert r.status_code == 200, r.json
        assert config.cfgApiKey == "sk-1234567890"
        assert config.cfgModel == "m2"
    finally:
        server._app = None


def test_config_form_unknown_key_is_400(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        r = _request("post", "/api/config/form", {"values": {"nope.value": 1}})
        assert r.status_code == 400
        assert "unknown config key" in r.json["error"]
        r = _request("post", "/api/config/form", {"values": {
            "agent.max_iters": 99}})
        assert r.status_code == 200, r.json
        assert config.agent_max_iters == 5
    finally:
        server._app = None


def test_config_yaml_redaction_and_save(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        _request("post", "/api/config/form", {"values": {
            "agent.endpoint": "https://api.test/v1",
            "agent.api_key": "sk-1234567890",
            "network.wifi_ssid": "HomeNet",
            "network.wifi_pass": "wifipass",
            "security.auth_token": ""}})
        r = _request("get", "/api/config/yaml")
        assert r.status_code == 200, r.json
        assert r.json["redacted"] is True
        assert "sk-1234567890" not in r.json["yaml"]
        assert "wifipass" not in r.json["yaml"]
        assert "****" in r.json["yaml"]
        r = _request("get", "/api/config/yaml?secrets=1")
        assert r.status_code == 200, r.json
        assert r.json["redacted"] is False
        assert "sk-1234567890" in r.json["yaml"]
        assert "wifipass" in r.json["yaml"]
        # Save a full document: comments survive when normalization is a no-op.
        text = r.json["yaml"].replace(
            "# Talaria Agent (micro) - configuration", "# hand note")
        r = _request("post", "/api/config/yaml", {"yaml": text})
        assert r.status_code == 200, r.json
        assert r.json["ok"] is True
        assert "# hand note" in open("config.yaml").read()
        assert config.cfgApiKey == "sk-1234567890"
    finally:
        server._app = None


def test_config_yaml_masked_save_preserves_secrets(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        _request("post", "/api/config/form", {"values": {
            "agent.endpoint": "https://api.test/v1",
            "agent.api_key": "sk-1234567890",
            "network.wifi_ssid": "HomeNet",
            "network.wifi_pass": "wifipass"}})
        r = _request("get", "/api/config/yaml")
        r = _request("post", "/api/config/yaml", {"yaml": r.json["yaml"]})
        assert r.status_code == 200, r.json
        assert r.json["masked_secrets_preserved"] is True
        assert config.cfgApiKey == "sk-1234567890"
        assert config.cfgPass == "wifipass"
    finally:
        server._app = None


def test_config_yaml_invalid_is_400(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        r = _request("post", "/api/config/yaml", {"yaml": "a: [1, 2\n"})
        assert r.status_code == 400
        assert "invalid YAML" in r.json["error"]
        r = _request("post", "/api/config/yaml", {"yaml": "- one\n- two\n"})
        assert r.status_code == 400
        assert "mapping" in r.json["error"]
        r = _request("post", "/api/config/yaml", {"yaml": "# comments only\n"})
        assert r.status_code == 400
        assert "empty" in r.json["error"]
    finally:
        server._app = None


def test_files_save_config_yaml_reloads(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        # config.yaml lives at flash `/` outside the locked Files home —
        # the system hatch owns it; the Config page remains primary.
        r = _request("post", "/api/system/files/save", {
            "path": "config.yaml",
            "content": "agent:\n  model: hand-edited\n"
                       "  endpoint: https://api.test/v1\n",
        })
        assert r.status_code == 200, r.json
        assert r.json.get("reloaded") is True
        assert config.cfgModel == "hand-edited"
        r = _request("post", "/api/system/files/save", {
            "path": "config.yaml", "content": "agent: [broken\n"})
        assert r.status_code == 400
        assert "invalid config.yaml" in r.json["error"]
        # The locked Files endpoint must refuse config.yaml outright.
        r = _request("post", "/api/files/save", {
            "path": "config.yaml", "content": "agent:\n  model: x\n",
        })
        assert r.status_code == 400
    finally:
        server._app = None


def test_old_flat_config_endpoint_still_works(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        r = _request("post", "/api/config", {
            "chat_entry_chars": 6000,
            "chat_log_max_kb": 400,
            "chat_log_keep_kb": 300,
            "chat_restore_turns": 10,
        })
        assert r.status_code == 200, r.json
        assert config.cfgChatEntryChars == 6000
        assert config.cfgChatLogMaxKB == 400
        assert config.cfgChatLogKeepKB == 300
        assert config.cfgChatRestoreTurns == 10
        r = _request("get", "/api/config")
        assert r.status_code == 200
        assert r.json["chat_entry_chars"] == 6000
    finally:
        server._app = None
