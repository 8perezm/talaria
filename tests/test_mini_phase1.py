# test_mini_phase1.py — Phase 1: prompt tiers + provider fallback + agent_core.
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_core
import agent_tools
import config
import llm
import prompt
import providers
import server
from tools import registry


def _setup(tmp_path, monkeypatch, fallback=True):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1
    config.cfgEndpoint = "https://api.primary/v1"
    config.cfgApiKey = "primary-key-123456"
    config.cfgModel = "primary-model"
    if fallback:
        config.cfgFallbackEndpoint = "https://api.fallback/v1"
        config.cfgFallbackKey = "fallback-key-123456"
        config.cfgFallbackModel = "fallback-model"
    else:
        config.cfgFallbackEndpoint = ""
        config.cfgFallbackKey = ""
        config.cfgFallbackModel = ""
    config.agent_max_iters = 3
    config.cfgAuthToken = ""
    try:
        import net
        net.apMode = False
    except Exception:
        pass
    server._app = None


def _tool_call_body(first="c1"):
    return json.dumps({"choices": [{"message": {
        "content": None,
        "tool_calls": [{"id": first, "type": "function",
                        "function": {"name": "get_status", "arguments": "{}"}}]}}]})


# ---- 1. prompt tiers ----

def test_tier_order_and_legacy_content(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    p = prompt.buildMiniPrompt()
    assert isinstance(p, str)
    i_stable = p.find("[stable]")
    i_ctx = p.find("[context]")
    i_vol = p.find("[volatile]")
    assert 0 <= i_stable < i_ctx < i_vol
    # all legacy content preserved verbatim
    assert "You are Talaria Agent" in p
    assert "Enabled device tools:" in p
    assert "get_status" in p
    assert "You have full general knowledge. Answer ordinary questions" in p
    assert "Never reply that you lack knowledge" in p
    assert "Use a tool ONLY when the request needs live device state" in p
    assert "Keep chat and acknowledgements short" in p
    assert "Always finish with a plain-text reply summarizing tool" in p
    assert "[dev ip=" in p


def test_context_missing_skipped(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    assert not os.path.exists(".context.md")
    p = prompt.buildMiniPrompt()
    assert "[context]" in p
    assert "Project context" not in p


def test_context_included_when_present(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    with open(".context.md", "w") as f:
        f.write("hello-context")
    assert "hello-context" in prompt.buildMiniPrompt()


def test_context_oversized_truncated(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    with open(".context.md", "w") as f:
        f.write("Q" * 2000)
    p = prompt.buildMiniPrompt()
    assert p.count("Q") == 1024
    assert "Q" * 1025 not in p


def test_memory_in_context_tier(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    assert agent_tools.appendMemoryFact("basil-fact")
    p = prompt.buildMiniPrompt()
    assert "basil-fact" in p
    assert p.find("basil-fact") > p.find("[context]")


# ---- 2. frozen-per-turn prompt ----

def test_prompt_built_once_per_turn(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    calls = {"n": 0}
    orig = prompt.buildMiniPrompt

    def counting():
        calls["n"] += 1
        return orig()

    monkeypatch.setattr(prompt, "buildMiniPrompt", counting)
    bodies = []

    def fake_post(body):
        bodies.append(json.loads(body))
        if len(bodies) == 1:
            return True, _tool_call_body(), 200
        return True, json.dumps({"choices": [{"message": {"content": "done"}}]}), 200

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLMWithTools("hi", [], {}) == "done"
    assert calls["n"] == 1
    assert bodies[0]["messages"][0]["content"] == bodies[1]["messages"][0]["content"]


def test_legacy_callllm_uses_mini_prompt(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    seen = {}

    def fake_post(body):
        seen["req"] = json.loads(body)
        return True, json.dumps({"choices": [{"message": {"content": "ok"}}]}), 200

    monkeypatch.setattr(llm, "postLLM", fake_post)
    assert llm.callLLM("hi") == "ok"
    assert "[stable]" in seen["req"]["messages"][0]["content"]


# ---- 3. providers ----

def test_get_providers_order(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    plist = providers.getProviders()
    assert len(plist) == 2
    assert plist[0][0].endswith("/chat/completions") and "primary" in plist[0][0]
    assert plist[0][1] == "primary-key-123456" and plist[0][2] == "primary-model"
    assert "fallback" in plist[1][0] and plist[1][2] == "fallback-model"


def test_get_providers_no_fallback(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    assert len(providers.getProviders()) == 1


def test_should_failover_matrix():
    assert providers.shouldFailover(False, 0) is True
    assert providers.shouldFailover(True, 429) is True
    assert providers.shouldFailover(True, 500) is True
    assert providers.shouldFailover(True, 503) is True
    assert providers.shouldFailover(True, 401) is False
    assert providers.shouldFailover(True, 400) is False
    assert providers.shouldFailover(True, 200) is False


# ---- 4. postLLM failover ----

def test_postllm_failover_429_then_success(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    calls = []

    def fake_raw(url, body, headers):
        calls.append(url)
        if len(calls) == 1:
            assert "primary" in url
            return True, '{"error":"slow down"}', 429
        assert "fallback" in url
        assert json.loads(body)["model"] == "fallback-model"
        assert headers.get("Authorization") == "Bearer fallback-key-123456"
        return True, json.dumps({"choices": [{"message": {"content": "ok"}}]}), 200

    monkeypatch.setattr(llm, "_post_raw", fake_raw)
    ok, resp, code = llm.postLLM(json.dumps({"model": "primary-model", "messages": []}))
    assert (ok, code) == (True, 200) and len(calls) == 2


def test_postllm_401_does_not_failover(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    calls = []

    def fake_raw(url, body, headers):
        calls.append(url)
        return True, '{"error":"bad key"}', 401

    monkeypatch.setattr(llm, "_post_raw", fake_raw)
    ok, resp, code = llm.postLLM("{}")
    assert (ok, code) == (True, 401) and len(calls) == 1


def test_postllm_transport_failover(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    calls = []

    def fake_raw(url, body, headers):
        calls.append(url)
        if len(calls) == 1:
            return False, "conn reset", 0
        return True, "{}", 200

    monkeypatch.setattr(llm, "_post_raw", fake_raw)
    ok, resp, code = llm.postLLM("{}")
    assert (ok, code) == (True, 200) and len(calls) == 2


def test_postllm_no_fallback_exact_errors(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    calls = []

    def fake_fail(url, body, headers):
        calls.append(url)
        return False, "boom", 0

    monkeypatch.setattr(llm, "_post_raw", fake_fail)
    assert llm.postLLM("{}") == (False, "boom", 0)

    def fake_401(url, body, headers):
        return True, "unauth", 401

    monkeypatch.setattr(llm, "_post_raw", fake_401)
    assert llm.postLLM("{}") == (True, "unauth", 401)
    assert len(calls) == 1  # transport path called exactly once


# ---- 5. streamChat failover ----

def test_stream_prefailure_retries_fallback_once(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    calls = []

    def fake_one(body, url, headers, timeout=45, tries=4):
        calls.append(url)
        if "primary" in url:
            yield ("status", (False, "conn reset", 0))
        else:
            assert json.loads(body)["model"] == "fallback-model"
            yield ("delta", "hi")
            yield ("status", (True, "", 200))

    monkeypatch.setattr(llm, "_stream_one_provider", fake_one)
    events = list(llm.streamChat(json.dumps({"model": "primary-model"})))
    assert ("delta", "hi") in events
    assert events[-1] == ("status", (True, "", 200))
    assert len(calls) == 2


def test_stream_no_failover_after_delta(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    calls = []

    def fake_one(body, url, headers, timeout=45, tries=4):
        calls.append(url)
        if "primary" in url:
            yield ("delta", "part")
            yield ("status", (False, "mid fail", 0))
        else:
            yield ("delta", "SHOULD NOT HAPPEN")
            yield ("status", (True, "", 200))

    monkeypatch.setattr(llm, "_stream_one_provider", fake_one)
    events = list(llm.streamChat("{}"))
    assert ("delta", "part") in events
    assert events[-1] == ("status", (False, "mid fail", 0))
    assert len(calls) == 1  # never duplicated onto the fallback


# ---- 6. agent_core budgets ----

def _always_tool_post(counter):
    def fake_post(body):
        counter["n"] += 1
        return True, _tool_call_body("c%d" % counter["n"]), 200
    return fake_post


def test_runturn_max_iters_1(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    counter = {"n": 0}
    monkeypatch.setattr(llm, "postLLM", _always_tool_post(counter))
    out = {}
    reply = agent_core.runTurn("hi", [], out, max_iters=1)
    # loop iteration + the tool-free summary retry
    assert counter["n"] == 2
    assert reply.startswith("Ran ") and "get_status" in reply


def test_runturn_max_iters_5(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    counter = {"n": 0}
    monkeypatch.setattr(llm, "postLLM", _always_tool_post(counter))
    reply = agent_core.runTurn("hi", [], {}, max_iters=5)
    # 5 loop iterations + the tool-free summary retry
    assert counter["n"] == 6
    assert reply.startswith("Ran ")


def test_runturn_clamps(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    counter = {"n": 0}
    monkeypatch.setattr(llm, "postLLM", _always_tool_post(counter))
    agent_core.runTurn("hi", [], {}, max_iters=99)
    assert counter["n"] == 6  # clamped to 5, plus the summary retry
    counter["n"] = 0
    agent_core.runTurn("hi", [], {}, max_iters=0)
    assert counter["n"] == 2  # clamped to 1, plus the summary retry


def test_runturn_default_from_config(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    config.agent_max_iters = 2
    counter = {"n": 0}
    monkeypatch.setattr(llm, "postLLM", _always_tool_post(counter))
    agent_core.runTurn("hi", [], {})
    assert counter["n"] == 3  # 2 iterations + the summary retry


# ---- 7. config + /api/agent ----

def test_config_fallback_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config.saveAgentOnly("https://p/v1", "k1", "m1",
                         "https://f/v1", "fk", "fm", 4)
    config.cfgEndpoint = config.cfgApiKey = config.cfgModel = ""
    config.cfgFallbackEndpoint = config.cfgFallbackKey = config.cfgFallbackModel = ""
    config.agent_max_iters = 3
    config.loadConfig()
    assert (config.cfgEndpoint, config.cfgApiKey, config.cfgModel) == \
        ("https://p/v1", "k1", "m1")
    assert (config.cfgFallbackEndpoint, config.cfgFallbackKey,
            config.cfgFallbackModel) == ("https://f/v1", "fk", "fm")
    assert config.agent_max_iters == 4


def test_save_agent_only_old_signature_preserves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config.saveAgentOnly("https://p/v1", "k1", "m1",
                         "https://f/v1", "fk", "fm", 4)
    config.saveAgentOnly("https://p2/v1", "k2", "m2")  # old 3-arg call
    assert config.cfgFallbackEndpoint == "https://f/v1"
    assert config.agent_max_iters == 4
    config.loadConfig()  # persisted file must agree
    assert config.cfgFallbackEndpoint == "https://f/v1"
    assert config.cfgEndpoint == "https://p2/v1"


def test_agent_get_payload_masked(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    payload = server._agent_get_payload()
    assert payload["fallback_endpoint"] == "https://api.fallback/v1"
    assert payload["fallback_model"] == "fallback-model"
    assert payload["agent_max_iters"] == 3
    assert payload["fallback_key_masked"] == config.maskedKey("fallback-key-123456")
    blob = json.dumps(payload)
    assert "fallback-key-123456" not in blob
    assert "primary-key-123456" not in blob


def test_agent_apply_post_ignores_unknown(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=False)
    err, res = server._agent_apply_post({"endpoint": "https://api.primary/v1",
                                         "bogus_key": 123,
                                         "fallback_model": "new-fb",
                                         "max_iters": 5})
    assert err is None and res["ok"] is True
    assert config.cfgFallbackModel == "new-fb"
    assert config.agent_max_iters == 5
    # invalid iters preserve the current value
    err, _ = server._agent_apply_post({"endpoint": "https://api.primary/v1",
                                       "max_iters": "nonsense"})
    assert err is None and config.agent_max_iters == 5


def test_agent_http_get_post(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, fallback=True)
    from microdot.test_client import TestClient

    async def _do():
        client = TestClient(server.get_app())
        r1 = await client.get("/api/agent")
        assert r1.status_code == 200
        assert r1.json["fallback_endpoint"] == "https://api.fallback/v1"
        assert "fallback-key-123456" not in json.dumps(r1.json)
        r2 = await client.post(
            "/api/agent", headers={"Content-Type": "application/json"},
            body=json.dumps({"endpoint": "https://api.primary/v1",
                             "mystery": "ignored",
                             "fallback_model": "http-fb"}))
        assert r2.status_code == 200
        assert config.cfgFallbackModel == "http-fb"

    asyncio.run(_do())
