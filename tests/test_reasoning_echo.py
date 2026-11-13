# test_reasoning_echo.py - tool continuations must echo the model's reasoning.
#
# DeepSeek reasoning models require `reasoning_content` on the assistant message
# that carries tool_calls. Without it the provider accepts the request and then
# never responds, which surfaces as a hung turn until the socket timeout.
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs  # noqa: E402

stubs.install()

from tools import registry  # noqa: E402
import config  # noqa: E402
import llm  # noqa: E402


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.test/v1"
    config.cfgApiKey = "k"
    config.cfgModel = "m"


def test_reasoning_content_echoed_on_tool_continuation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = {"n": 0, "second": None}

    def fake_post(body):
        seen["n"] += 1
        if seen["n"] == 1:
            r = {"choices": [{"message": {
                "content": None,
                "reasoning_content": "I will read the heap first.",
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "get_status",
                                             "arguments": "{}"}}]}}]}
            return True, json.dumps(r), 200
        seen["second"] = json.loads(body)
        return True, json.dumps(
            {"choices": [{"message": {"content": "the heap is fine"}}]}), 200

    monkeypatch.setattr(llm, "postLLM", fake_post)
    reply = llm.callLLMWithTools("how is the heap?", None, {}, max_iters=2)

    assert "the heap is fine" in reply
    assistant = [m for m in seen["second"]["messages"]
                 if m.get("role") == "assistant" and m.get("tool_calls")]
    assert assistant, "expected an assistant tool_calls message"
    assert assistant[-1].get("reasoning_content") == "I will read the heap first."
