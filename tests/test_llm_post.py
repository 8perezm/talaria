import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import llm


def test_split_url():
    assert llm._split_url("https://api.deepinfra.com/v1/openai/chat/completions") == \
        (True, "api.deepinfra.com", 443, "/v1/openai/chat/completions")
    assert llm._split_url("http://lan:8000/x") == (False, "lan", 8000, "/x")


def test_resolve_prefers_ipv4():
    import socket
    sa = llm._resolve_ipv4("localhost", 80)
    assert isinstance(sa, tuple) and sa[0] == "127.0.0.1"
    all4 = llm._resolve_all_ipv4("localhost", 80)
    assert all4 and all4[0][0] == "127.0.0.1"


def test_post_raw_live_deepinfra_401():
    # No API key -> DeepInfra answers 401 JSON fast. Proves TLS + HTTP/1.0
    # + Content-Length parsing on the raw-socket path (no key needed).
    import json
    ok, text, code = llm._post_raw(
        "https://api.deepinfra.com/v1/openai/chat/completions",
        json.dumps({"model": "x", "messages": [{"role": "user", "content": "hi"}]}),
        {"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    assert ok, text
    assert code == 401, (code, text[:200])
    d = json.loads(text)
    assert "message" in str(d).lower() or "error" in str(d).lower()
