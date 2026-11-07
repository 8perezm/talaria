import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import server


def _deepinfra_like(n, pad=1400):
    parts = ['{"object":"list","data":[']
    for i in range(n):
        desc = ("d%d " % i) * (pad // 4)
        parts.append(
            '{"id":"org/model-%d","object":"model","created":0,'
            '"owned_by":"org","root":"org/model-%d","parent":null,'
            '"metadata":{"description":"%s","tags":["chat"]}}' % (i, i, desc)
        )
        if i < n - 1:
            parts.append(",")
    parts.append("]}")
    return "".join(parts)


def _chunks(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]


def test_split_url():
    assert server._split_url("https://api.deepinfra.com/v1/openai") == \
        (True, "api.deepinfra.com", 443, "/v1/openai")
    assert server._split_url("https://x/v1/chat/completions") == \
        (True, "x", 443, "/v1/chat/completions")
    assert server._split_url("http://lan:8000/v1") == \
        (False, "lan", 8000, "/v1")


def test_scan_small_one_byte_chunks():
    body = '{"object":"list","data":[{"id":"a"},{"id":"b"}]}'
    assert server._scan_model_ids(_chunks(body, 1)) == ["a", "b"]


def test_scan_large_512b_chunks():
    body = _deepinfra_like(70)
    assert len(body) > 90000  # DeepInfra-scale payload
    ids = server._scan_model_ids(_chunks(body, 512))
    assert len(ids) == 70
    assert ids[0] == "org/model-0"
    assert ids[69] == "org/model-69"


def test_scan_caps_at_max_ids():
    body = _deepinfra_like(250)
    ids = server._scan_model_ids(_chunks(body, 512))
    assert len(ids) == server._MODELS_MAX_IDS
    assert ids[0] == "org/model-0"


def test_scan_no_data_wrapper():
    assert server._scan_model_ids(['{"models":[]}']) == []
    assert server._scan_model_ids([]) == []
