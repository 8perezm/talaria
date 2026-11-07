import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import config


def test_url_normalizers():
    assert config.chatCompletionsUrl("https://api.openai.com/v1") == \
        "https://api.openai.com/v1/chat/completions"
    assert config.chatCompletionsUrl("https://x/v1/") == "https://x/v1/chat/completions"
    assert config.chatCompletionsUrl("https://x/v1/chat/completions") == \
        "https://x/v1/chat/completions"
    assert config.modelsUrl("https://api.openai.com/v1") == "https://api.openai.com/v1/models"
    assert config.modelsUrl("https://x/v1/chat/completions") == "https://x/v1/models"


def test_masked_key():
    assert config.maskedKey("ab") == "****"
    assert config.maskedKey("sk-1234567890") == "sk-1****90"


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config.saveWifiOnly("MyNet", "secret")
    config.saveAgentOnly("https://api.openai.com/v1", "k123", "gpt-4o-mini")
    config.saveToolsMask(5)
    config.saveAuthToken("supersecret1")
    # reset globals then reload
    config.cfgSsid = config.cfgPass = config.cfgEndpoint = ""
    config.loadConfig()
    assert config.cfgSsid == "MyNet"
    assert config.cfgPass == "secret"
    assert config.cfgEndpoint == "https://api.openai.com/v1"
    assert config.cfgApiKey == "k123"
    assert config.cfgModel == "gpt-4o-mini"
    assert config.gToolsMask == 5
    assert config.cfgAuthToken == "supersecret1"
