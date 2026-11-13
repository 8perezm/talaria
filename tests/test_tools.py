import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import agent_tools
from tools import registry


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    import config
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1


def test_registry_order_and_count(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    names = [t["name"] for t in agent_tools.TOOL_REGISTRY]
    assert names == ["get_status", "gpio_write", "gpio_read", "adc_read", "wifi_scan",
                     "mem_save", "mem_read", "restart_device", "blink", "web_fetch",
                     "memory", "skills", "skill_view", "session_search", "cron",
                     "todo", "delegate_task", "exec_py",
                     "read_file", "write_file", "patch_file", "search_files",
                     "run_script"]
    assert agent_tools.all_tools_mask() == 0x7FFFFF


def test_pins_classic_and_s3(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.pinCanWrite(2)
    assert not agent_tools.pinCanWrite(34)
    assert agent_tools.pinCanRead(34)
    assert agent_tools.pinCanADC(36)
    # S3 extras accepted via union
    assert agent_tools.pinCanWrite(8)
    assert agent_tools.pinCanWrite(40)
    assert agent_tools.pinCanADC(8)


def test_gpio_write_and_blink(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    s = agent_tools.execTool("gpio_write", {"pin": 2, "level": 1})
    import json
    assert json.loads(s)["ok"] is True
    s = agent_tools.execTool("gpio_write", {"pin": 34, "level": 1})
    assert "error" in json.loads(s)
    s = agent_tools.execTool("blink", {"pin": 2, "count": 2, "on_ms": 50, "off_ms": 50})
    assert json.loads(s)["ok"] is True
    assert json.loads(s)["blinks"] == 2
    s = agent_tools.execTool("nope", {})
    assert "unknown tool" in s


def test_memory_and_log(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert agent_tools.appendMemoryFact("my plant is a basil")
    mem = agent_tools.readMemoryFacts()
    assert "basil" in mem
    assert agent_tools.appendChatLog("hello", "hi there")
    msgs = []
    n = agent_tools.injectRecentLog(msgs, "something else", 8)
    assert n >= 2
    assert any(m["role"] == "user" for m in msgs)


def test_system_prompt_lists_enabled_only(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    import config
    # only get_status enabled
    config.gToolsMask = 1 << 0
    p = agent_tools.buildSystemPrompt()
    assert "get_status" in p
    assert "blink" not in p
