"""Conversation persistence: streamed turns are logged + tail restore API.

Regression for: "refresh the page and it forgot the conversation". The SSE
path used to stream the reply but never write chatlog.jsonl, so the device
had no context after a reload.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
import config
import llm
import net
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


def test_read_log_tail_order_and_cap(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("u1", "a1")
    assert agent_tools.appendChatLog("u2", "a2")
    tail, size = server._read_log_tail(agent_tools.LOG_PATH, 3)
    assert size > 0
    assert [e["content"] for e in tail] == ["a1", "u2", "a2"]
    assert tail[0]["role"] == "assistant"


def test_long_reply_survives_store_and_restore(tmp_path, monkeypatch):
    """A 6-7 paragraph answer must come back whole after a page reload.

    Regression: appendChatLog stored 1500 chars and _read_log_tail returned
    only 800, so the transcript showed roughly two paragraphs after refresh.
    """
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "cfgChatEntryChars", 6000)
    reply = ("Edinburgh is Scotland's capital. " * 30 + "\n\n") * 7
    reply = reply[:5500]
    assert agent_tools.appendChatLog("tell me about edinburgh", reply)
    tail, _ = server._read_log_tail(agent_tools.LOG_PATH, 20)
    assert tail[-1]["role"] == "assistant"
    assert tail[-1]["content"] == reply
    assert len(tail[-1]["content"]) > 800


def test_twenty_turn_conversation_is_retained(tmp_path, monkeypatch):
    """The rolling log must keep 20 turns of multi-paragraph replies."""
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "cfgChatEntryChars", 4000)
    paragraph = "Edinburgh has a long and layered history. " * 25  # ~1.2 KB
    reply = (paragraph + "\n\n") * 3  # a few paragraphs, ~3.6 KB
    for i in range(20):
        assert agent_tools.appendChatLog("question %d" % i, reply)
    # The chat page asks for 40 lines = 20 turns.
    tail, size = server._read_log_tail(agent_tools.LOG_PATH, 40)
    assert len(tail) == 40
    assert tail[0]["role"] == "user"
    assert tail[1]["role"] == "assistant"
    assert all(len(e["content"]) == len(reply) for e in tail[1::2])
    # Host reads translate CRLF, so compare against the budget, not st_size.
    assert size > 60000
    assert size < agent_tools.LOG_MAX_BYTES


def test_chunked_tail_reader_matches_last_lines(tmp_path, monkeypatch):
    """Backwards block reads must return exactly the last N complete lines."""
    _setup(tmp_path, monkeypatch)
    path = "tailtest.jsonl"
    with open(path, "w") as f:
        for i in range(100):
            f.write(json.dumps({"r": "user", "c": "line %d " % i + "x" * 50}) + "\n")
    # 64-byte blocks force many seeks, and lines are longer than one block.
    tail, total = server._read_log_tail(path, 5, block_bytes=64)
    assert total > 0
    assert [e["content"].split()[1] for e in tail] == ["95", "96", "97", "98", "99"]
    assert [e["role"] for e in tail] == ["user"] * 5


def test_chunked_tail_reader_handles_line_larger_than_block(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    path = "tailtest.jsonl"
    big = "z" * 5000
    with open(path, "w") as f:
        f.write(json.dumps({"r": "assistant", "c": "first"}) + "\n")
        f.write(json.dumps({"r": "assistant", "c": big}) + "\n")
        f.write(json.dumps({"r": "user", "c": "last"}) + "\n")
    tail, _ = server._read_log_tail(path, 2, max_chars=6000, block_bytes=128)
    assert [e["content"] for e in tail] == [big, "last"]


def test_log_rotation_keeps_newest_and_respects_budget(tmp_path, monkeypatch):
    """Chunked rotation trims to the newest slice without reading it all."""
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "cfgChatEntryChars", 2000)
    monkeypatch.setattr(config, "cfgChatLogMaxKB", config.CHAT_LOG_MAX_KB_MIN)
    monkeypatch.setattr(config, "cfgChatLogKeepKB", config.CHAT_LOG_KEEP_KB_MIN)
    text = "y" * 1000
    for i in range(80):  # ~160 KB written -> several rotations
        assert agent_tools.appendChatLog("q%d" % i, text)
    size = os.stat(agent_tools.LOG_PATH)[6]
    assert size <= (config.CHAT_LOG_MAX_KB_MIN * 1024) + 4096
    assert not os.path.exists(agent_tools.LOG_PATH + ".tmp")
    tail, _ = server._read_log_tail(agent_tools.LOG_PATH, 2, max_chars=2000)
    assert tail[-1]["role"] == "assistant"
    assert tail[-1]["content"] == text
    every, _ = server._read_log_tail(agent_tools.LOG_PATH, 200, max_chars=2000)
    assert all(e["content"] != "q0" for e in every)


def test_memory_default_uses_configured_restore_turns(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "cfgChatRestoreTurns", 3)
    for i in range(6):
        assert agent_tools.appendChatLog("q%d" % i, "a%d" % i)
    res = _request("get", "/api/memory")
    assert res.status_code == 200
    assert [e["content"] for e in res.json["log_tail"]] == [
        "q3", "a3", "q4", "a4", "q5", "a5"]


def test_chat_entry_chars_config_endpoint(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = _request("post", "/api/config", {"chat_entry_chars": 9000})
    assert res.status_code == 200
    assert res.json["chat_entry_chars"] == 9000
    got = _request("get", "/api/config")
    assert got.status_code == 200
    assert got.json["chat_entry_chars"] == 9000
    # and the configured cap is what the restore path now applies
    assert agent_tools.appendChatLog("q", "x" * 12000)
    tail, _ = server._read_log_tail(agent_tools.LOG_PATH, 20)
    assert len(tail[-1]["content"]) == 9000
    config.cfgChatEntryChars = config.DEFAULT_CHAT_ENTRY_CHARS


def test_memory_endpoint_tail_param(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for i in range(8):
        assert agent_tools.appendChatLog("q%d" % i, "a%d" % i)
    res = _request("get", "/api/memory?tail=4")
    assert res.status_code == 200
    # last 4 lines = q6, a6, q7, a7
    assert [e["content"] for e in res.json["log_tail"]] == ["q6", "a6", "q7", "a7"]


def test_clear_log_endpoint_removes_history(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("remember me", "sure")
    res = _request("post", "/api/memory", {"clear_log": True})
    assert res.status_code == 200
    assert res.json["cleared_log"] is True
    assert not os.path.exists(agent_tools.LOG_PATH)
    # facts are not touched by clearing the chat
    assert agent_tools.appendMemoryFact("basil")


def test_stream_turn_is_persisted(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert not os.path.exists(agent_tools.LOG_PATH)

    def fake_stream(body):
        yield ("delta", "Hello")
        yield ("delta", " world")
        yield ("status", (True, "", 200))

    monkeypatch.setattr(llm, "streamChat", fake_stream)
    res = _request("post", "/api/chat-stream", {"message": "hi"})
    assert res.status_code == 200
    assert '"delta": "Hello"' in res.text
    assert "[DONE]" in res.text

    with open(agent_tools.LOG_PATH, "r") as f:
        lines = [json.loads(ln) for ln in f.read().splitlines() if ln.strip()]
    assert {"r": "user", "c": "hi"} in lines
    assert {"r": "assistant", "c": "Hello world"} in lines


def test_stream_tool_fallback_is_not_logged_twice(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def fake_stream(body):
        yield ("tools", None)

    monkeypatch.setattr(llm, "streamChat", fake_stream)
    res = _request("post", "/api/chat-stream", {"message": "blink"})
    assert res.status_code == 200
    assert "need_tools" in res.text
    # /api/chat owns that turn; no half-turn in the log.
    assert not os.path.exists(agent_tools.LOG_PATH)


def test_stream_upstream_error_is_not_logged(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def fake_stream(body):
        yield ("status", (True, "bad key", 401))

    monkeypatch.setattr(llm, "streamChat", fake_stream)
    res = _request("post", "/api/chat-stream", {"message": "hi"})
    assert res.status_code == 200
    assert "upstream HTTP 401" in res.text
    assert not os.path.exists(agent_tools.LOG_PATH)


def test_history_skips_log_when_client_sends_history(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendChatLog("old q", "old a")

    seen = {}

    def fake_post(body):
        seen["req"] = json.loads(body)
        return True, json.dumps({"choices": [{"message": {"content": "ok"}}]}), 200

    monkeypatch.setattr(llm, "postLLM", fake_post)
    llm.callLLMWithTools("new q", [{"role": "user", "content": "live q"},
                                   {"role": "assistant", "content": "live a"}], {})
    contents = [m["content"] for m in seen["req"]["messages"]]
    # live history only: the persisted log must not be duplicated in the prompt
    assert "live q" in contents and "old q" not in contents

    llm.callLLMWithTools("new q 2", [], {})
    contents = [m["content"] for m in seen["req"]["messages"]]
    assert "old q" in contents  # empty page -> device log restores context




