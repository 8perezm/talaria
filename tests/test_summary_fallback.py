# test_summary_fallback.py - a turn that ran tools must still end in prose.
#
# After a failed follow-up iteration (upstream error or exhausted budget) the
# device makes one compact, tool-free completion so the user gets a summary
# instead of a raw tool dump.
import json

import llm


def test_summary_request_is_tool_free(monkeypatch):
    seen = {}

    def fake_post(body):
        seen["body"] = body
        return True, json.dumps(
            {"choices": [{"message": {"content": "It worked."}}]}), 200

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm._summary_request("do it", "run_script: ok", "m1") == "It worked."

    sent = json.loads(seen["body"])
    assert sent["model"] == "m1"
    assert "tools" not in sent
    assert "run_script: ok" in sent["messages"][-1]["content"]


def test_summary_request_survives_upstream_failure(monkeypatch):
    monkeypatch.setattr(llm, "postLLM", lambda body: (False, "boom", 0))
    assert llm._summary_request("x", "y", "m") == ""


def test_summary_request_survives_bad_json(monkeypatch):
    monkeypatch.setattr(llm, "postLLM", lambda body: (True, "not json", 200))
    assert llm._summary_request("x", "y", "m") == ""


def test_summary_request_survives_empty_content(monkeypatch):
    monkeypatch.setattr(
        llm, "postLLM",
        lambda body: (True, json.dumps({"choices": [{"message": {}}]}), 200))
    assert llm._summary_request("x", "y", "m") == ""
