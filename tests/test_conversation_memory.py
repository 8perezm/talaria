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


def test_chat_page_restores_transcript_from_device_memory():
    path = os.path.join(os.path.dirname(__file__), "..", "www", "chat.html")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    assert "/api/memory?tail=20" in src
    assert "function restoreTranscript" in src
    # restored turns must seed history, or the next request loses context
    assert "history.push({role:m.role,content:m.content})" in src
    # clear button wipes both the view and the device log, and resets history
    assert 'id="clearbtn"' in src
    assert "function clearChat" in src
    assert "clear_log:true" in src
    assert "history=[]" in src


def test_clear_dialogs_are_in_page_modals():
    """No native confirm()/alert(): both pages use the styled modal."""
    base = os.path.join(os.path.dirname(__file__), "..", "www")
    for name in ("chat.html", "functions.html"):
        with open(os.path.join(base, name), encoding="utf-8") as f:
            src = f.read()
        assert "confirm(" not in src, "%s still calls a native confirm()" % name
        assert 'class="modal"' in src, "%s has no in-page modal" % name
        assert "modalcard" in src
