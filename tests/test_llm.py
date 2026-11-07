import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
from tools import registry
import config
import llm


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.test/v1"
    config.cfgApiKey = "k"
    config.cfgModel = "m"


def _resp_obj(payload):
    return {"choices": [{"message": {"content": payload}}]}


def test_tool_loop_single_call(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake_post(body):
        calls["n"] += 1
        req = json.loads(body)
        if calls["n"] == 1:
            assert any("get_status" in str(t) for t in [req.get("tools", "")])
            r = {"choices": [{"message": {
                "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                               "function": {"name": "get_status", "arguments": "{}"}}]}}]}
            return True, json.dumps(r), 200
        r = {"choices": [{"message": {"content": "heap is fine"}}]}
        return True, json.dumps(r), 200

    monkeypatch.setattr(llm, "postLLM", fake_post)
    out = {}
    reply = llm.callLLMWithTools("what is your heap?", [], out)
    assert reply == "heap is fine"
    assert "get_status" in out["tools_used"]
    # persisted to log
    assert os.path.exists("chatlog.jsonl")


def test_tool_loop_disabled_tool(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config.gToolsMask = 0  # nothing enabled -> buildSystemPrompt lists none
    config.gToolsMask = 1 << 0  # only get_status; blink disabled

    def fake_post(body):
        import json as _j
        req = _j.loads(body)
        names = [t["function"]["name"] for t in req.get("tools", [])]
        assert "blink" not in names
        return True, _j.dumps({"choices": [{"message": {"content": "ok"}}]}), 200

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLMWithTools("hi", [], {}) == "ok"


def test_upstream_error_passthrough(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(llm, "postLLM", lambda body: (True, '{"error":"bad"}', 401))
    assert llm.callLLMWithTools("hi", [], {}).startswith("ERROR: upstream HTTP 401")
