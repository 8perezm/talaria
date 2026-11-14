# test_config_yaml.py — config.yaml storage, migration and schema helpers.
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import config
import config_schema as schema
import yamlish


def _reset_globals():
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
    config.agent_max_tokens = config.DEFAULT_AGENT_MAX_TOKENS
    config.gToolsMask = 0


def test_yaml_storage_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    config.saveWifiOnly("HomeNet", "p@ss # word")
    config.saveAgentOnly("https://api.test/v1", "sk-secret-123456", "m")
    config.saveAuthToken("token-123")
    config.saveChatStorage(512, 300, 25)
    assert os.path.exists("config.yaml")
    assert not os.path.exists("config.json")
    text = open("config.yaml").read()
    assert "network:" in text and "wifi_ssid: HomeNet" in text
    assert "security:" in text and "auth_token: token-123" in text
    _reset_globals()
    config.loadConfig()
    assert (config.cfgSsid, config.cfgPass) == ("HomeNet", "p@ss # word")
    assert config.cfgEndpoint == "https://api.test/v1"
    assert config.cfgApiKey == "sk-secret-123456"
    assert config.cfgModel == "m"
    assert config.cfgAuthToken == "token-123"
    assert (config.cfgChatLogMaxKB, config.cfgChatLogKeepKB,
            config.cfgChatRestoreTurns) == (512, 300, 25)


def test_agent_max_tokens_is_schema_backed_and_clamped(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    field = [f for f in schema.FIELDS if f["key"] == "agent.max_tokens"]
    assert field and field[0]["default"] == config.DEFAULT_AGENT_MAX_TOKENS

    config.save_form({"agent.max_tokens": 3000})
    assert config.agent_max_tokens == 3000
    assert "max_tokens: 3000" in open("config.yaml").read()

    config.save_form({"agent.max_tokens": 10})
    assert config.agent_max_tokens == config.AGENT_MAX_TOKENS_MIN
    config.save_form({"agent.max_tokens": 9000})
    assert config.agent_max_tokens == config.AGENT_MAX_TOKENS_MAX


def test_legacy_json_migrates_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    legacy = {
        "wifi_ssid": "OldNet",
        "wifi_pass": "oldpass",
        "api_endpoint": "https://old/v1",
        "api_key": "old-key-123456",
        "api_model": "old-model",
        "auth_token": "oldtoken",
        "chat_entry_chars": 6000,
        "agent_max_iters": 4,
        "skills": {"write_approval": False},
        "agent": {"custom": "keep-agent-extra"},
        "tools_mask": 5,
        "tools": {"custom": "keep-tools-extra"},
        "future_key": {"keep": "me"},
    }
    with open("config.json", "w") as f:
        f.write(json.dumps(legacy))
    config.loadConfig()
    assert config.cfgSsid == "OldNet"
    assert config.cfgApiKey == "old-key-123456"
    assert config.agent_max_iters == 4
    assert config.gToolsMask == 5
    assert config.get_approval("skills") is False
    assert os.path.exists("config.yaml")
    assert os.path.exists("config.json.bak")
    assert not os.path.exists("config.json")
    # unknown keys survive the migration
    doc = yamlish.loads(open("config.yaml").read())
    assert doc["future_key"] == {"keep": "me"}
    assert doc["agent"]["custom"] == "keep-agent-extra"
    assert doc["tools"]["custom"] == "keep-tools-extra"
    assert doc["tools"]["mask"] == 5


def test_form_payload_masks_secrets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    config.saveAgentOnly("https://api.test/v1", "sk-1234567890", "m")
    payload = config.form_payload()
    by_key = {f["key"]: f for f in payload["fields"]}
    assert by_key["agent.endpoint"]["value"] == "https://api.test/v1"
    assert by_key["agent.api_key"]["value"] == ""
    assert by_key["agent.api_key"]["has_value"] is True
    assert by_key["agent.api_key"]["masked"] == "sk-1****90"
    assert by_key["security.auth_token"]["value"] == "open"
    assert payload["path"] == "config.yaml"
    assert [c["id"] for c in payload["categories"]] == list(schema.CATEGORY_ORDER)


def test_save_form_blank_secret_keeps_stored_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    config.saveAgentOnly("https://api.test/v1", "sk-keep-123456", "m")
    out = config.save_form({
        "agent.model": "new-model",
        "agent.api_key": "",
        "chat.entry_chars": 7000,
        "chat.log_max_kb": 100,
        "chat.log_keep_kb": 200,  # clamps to max-32
    })
    assert out["restart"] is False
    assert config.cfgApiKey == "sk-keep-123456"
    assert config.cfgModel == "new-model"
    assert config.cfgChatEntryChars == 7000
    assert config.cfgChatLogMaxKB == 100
    assert config.cfgChatLogKeepKB == 68


def test_save_form_marks_network_restart(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    config.saveWifiOnly("Old", "pass")
    out = config.save_form({"network.wifi_ssid": "New"})
    assert out["restart"] is True
    assert config.cfgSsid == "New"


def test_raw_yaml_redaction_and_masked_save(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    config.saveAgentOnly("https://api.test/v1", "sk-1234567890", "m")
    config.saveWifiOnly("HomeNet", "wifipass")
    text, redacted = config.yaml_text(redact=True)
    assert redacted is True
    assert "sk-1234567890" not in text
    assert "wifipass" not in text
    assert "****" in text
    # Saving the redacted document must preserve the live secrets.
    config.save_raw_yaml(text)
    assert config.cfgApiKey == "sk-1234567890"
    assert config.cfgPass == "wifipass"
    assert config.cfgEndpoint == "https://api.test/v1"


def test_raw_yaml_preserves_hand_comments(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    config.saveConfig("HomeNet", "pass", "https://api.test/v1",
                      "sk-1234567890", "m")
    text = open("config.yaml").read()
    text = text.replace("# Talaria Agent (micro) - configuration",
                        "# my hand-written note")
    config.save_raw_yaml(text)
    assert "# my hand-written note" in open("config.yaml").read()


def test_raw_yaml_rejects_non_mapping(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    try:
        config.save_raw_yaml("- one\n- two\n")
    except ValueError as exc:
        assert "mapping" in str(exc)
    else:
        raise AssertionError("non-mapping YAML was accepted")


def test_raw_yaml_rejects_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    try:
        config.save_raw_yaml("# only comments\n")
    except ValueError as exc:
        assert "empty" in str(exc)
    else:
        raise AssertionError("empty YAML was accepted")


def test_dump_doc_uses_schema_order(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    config.saveAgentOnly("https://api.test/v1", "sk-1234567890", "m")
    text = open("config.yaml").read()
    assert text.index("endpoint:") < text.index("model:")
    assert text.index("model:") < text.index("api_key:")
    assert text.index("api_key:") < text.index("max_iters:")


def test_bad_hand_edit_falls_back_instead_of_aborting_boot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    with open("config.yaml", "w") as f:
        f.write("agent:\n  max_iters: not-a-number\n  endpoint: https://api.test/v1\n")
    config.loadConfig()
    assert config.agent_max_iters == config.DEFAULT_AGENT_MAX_ITERS
    assert config.cfgEndpoint == "https://api.test/v1"


def test_approval_defaults_and_legacy_sections(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _reset_globals()
    assert config.get_approval("memory", False) is False
    assert config.get_approval("skills", True) is True
    with open("config.json", "w") as f:
        f.write(json.dumps({"memory": {"write_approval": True},
                            "skills": {"write_approval": False}}))
    assert config.get_approval("memory", False) is True
    assert config.get_approval("skills", True) is False
