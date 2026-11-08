# test_yamlish.py — the device YAML subset used by config.yaml.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import pytest

import yamlish


SAMPLE = """\
# leading comment
_config_version: 1

agent:
  endpoint: https://api.example.com/v1   # inline comment
  model: "deepseek-ai/DeepSeek-V4.1"
  api_key: sk-1****90
  max_iters: 3

network:
  wifi_ssid: 'HomeNet'
  wifi_pass: "p@ss # word"
  flags: [fast, "stable", 'no-comment']
  empty:
  disabled: false
  nil: null
  ratio: 1.5

tools:
  mask: 0x10
"""


def test_loads_nested_and_scalars():
    doc = yamlish.loads(SAMPLE)
    assert doc["_config_version"] == 1
    assert doc["agent"]["endpoint"] == "https://api.example.com/v1"
    assert doc["agent"]["model"] == "deepseek-ai/DeepSeek-V4.1"
    assert doc["agent"]["max_iters"] == 3
    assert doc["network"]["wifi_ssid"] == "HomeNet"
    assert doc["network"]["wifi_pass"] == "p@ss # word"
    assert doc["network"]["flags"] == ["fast", "stable", "no-comment"]
    assert doc["network"]["empty"] is None
    assert doc["network"]["disabled"] is False
    assert doc["network"]["nil"] is None
    assert doc["network"]["ratio"] == 1.5
    assert doc["tools"]["mask"] == 0x10


def test_roundtrip_is_stable():
    doc = yamlish.loads(SAMPLE)
    text = yamlish.dumps(doc)
    assert yamlish.loads(text) == doc


def test_inline_map_and_list():
    doc = yamlish.loads('x: {a: 1, b: "two", c: [3, 4]}\n')
    assert doc == {"x": {"a": 1, "b": "two", "c": [3, 4]}}


def test_comments_inside_quotes_are_kept():
    doc = yamlish.loads('password: "a # b"  # real comment\n')
    assert doc["password"] == "a # b"


def test_quotes_escape():
    doc = yamlish.loads('msg: "line\\nnext\\t tab \\"quoted\\""\n')
    assert doc["msg"] == 'line\nnext\t tab "quoted"'
    assert yamlish.loads("msg: 'it''s fine'\n")["msg"] == "it's fine"


def test_dump_quotes_ambiguous_scalars():
    doc = {"a": "true", "b": "12", "c": "null", "d": " padded ", "e": "a: b", "f": ""}
    text = yamlish.dumps(doc)
    assert yamlish.loads(text) == doc
    assert '"true"' in text and '"12"' in text and '"null"' in text


def test_line_numbers_in_errors():
    with pytest.raises(yamlish.YamlError) as exc:
        yamlish.loads("a: 1\n  b: 2\n")
    assert "line" in str(exc.value)
    with pytest.raises(yamlish.YamlError):
        yamlish.loads("a: [1, 2\n")
    with pytest.raises(yamlish.YamlError):
        yamlish.loads("a: \"unterminated\n")
    with pytest.raises(yamlish.YamlError):
        yamlish.loads("a:\n\tb: 1\n")


def test_plain_url_is_not_a_mapping():
    doc = yamlish.loads("endpoint: https://x.example/a#frag\n")
    assert doc["endpoint"] == "https://x.example/a#frag"


def test_explicit_dump_order():
    doc = {"agent": {"max_iters": 3, "api_key": "x", "model": "m",
                     "endpoint": "https://e"}}
    text = yamlish.dumps(doc, {"agent": ["endpoint", "model", "api_key",
                                          "max_iters"]})
    assert text.index("endpoint") < text.index("model")
    assert text.index("model") < text.index("api_key")
    assert text.index("api_key") < text.index("max_iters")
