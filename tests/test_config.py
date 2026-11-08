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


def test_chat_entry_chars_roundtrip_and_clamp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert config.saveChatEntryChars(7000) == 7000
    config.cfgChatEntryChars = config.DEFAULT_CHAT_ENTRY_CHARS
    config.loadConfig()
    assert config.cfgChatEntryChars == 7000
    # out-of-range values clamp instead of disabling history
    assert config.saveChatEntryChars(10) == config.CHAT_ENTRY_CHARS_MIN
    assert config.saveChatEntryChars(10 ** 9) == config.CHAT_ENTRY_CHARS_MAX
    assert config.saveChatEntryChars("not-a-number") == config.CHAT_ENTRY_CHARS_MAX
    config.cfgChatEntryChars = config.DEFAULT_CHAT_ENTRY_CHARS


def test_chat_storage_roundtrip_and_clamp(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    out = config.saveChatStorage(512, 300, 25)
    assert out == {"chat_log_max_kb": 512, "chat_log_keep_kb": 300,
                   "chat_restore_turns": 25}
    config.cfgChatLogMaxKB = config.DEFAULT_CHAT_LOG_MAX_KB
    config.cfgChatLogKeepKB = config.DEFAULT_CHAT_LOG_KEEP_KB
    config.cfgChatRestoreTurns = config.DEFAULT_CHAT_RESTORE_TURNS
    config.loadConfig()
    assert (config.cfgChatLogMaxKB, config.cfgChatLogKeepKB,
            config.cfgChatRestoreTurns) == (512, 300, 25)
    # lowering the budget drags "keep" down, always leaving 32 KB headroom
    out = config.saveChatStorage(100, 200, 25)
    assert out["chat_log_max_kb"] == 100
    assert out["chat_log_keep_kb"] == 68
    # extreme values clamp instead of disabling the log
    out = config.saveChatStorage(1, 1, 0)
    assert out == {"chat_log_max_kb": config.CHAT_LOG_MAX_KB_MIN,
                   "chat_log_keep_kb": config.CHAT_LOG_KEEP_KB_MIN,
                   "chat_restore_turns": config.CHAT_RESTORE_TURNS_MIN}
    out = config.saveChatStorage(10 ** 9, 10 ** 9, 10 ** 9)
    assert out["chat_log_max_kb"] == config.CHAT_LOG_MAX_KB_MAX
    assert out["chat_log_keep_kb"] == config.CHAT_LOG_MAX_KB_MAX - 32
    assert out["chat_restore_turns"] == config.CHAT_RESTORE_TURNS_MAX
    config.cfgChatLogMaxKB = config.DEFAULT_CHAT_LOG_MAX_KB
    config.cfgChatLogKeepKB = config.DEFAULT_CHAT_LOG_KEEP_KB
    config.cfgChatRestoreTurns = config.DEFAULT_CHAT_RESTORE_TURNS


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
