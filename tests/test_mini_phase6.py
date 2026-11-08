# test_mini_phase6.py — Phase 6: todo + delegate_task + exec_py.
# Child runner is stubbed (monkeypatched runTurn) — no network in tests.
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import stubs

stubs.install()

import pytest

import agent_core
import agent_tools
import config
import delegate
import exec_py
import llm
import todo
from tools import registry


def _setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry.register_into_agent_tools()
    config.gToolsMask = (1 << len(registry.TOOL_REGISTRY)) - 1


@pytest.fixture(autouse=True)
def _clean():
    todo._reset()
    delegate._reset()
    agent_tools._ACTIVE_TOOL_ALLOW = None
    yield
    todo._reset()
    delegate._reset()
    agent_tools._ACTIVE_TOOL_ALLOW = None


def _fake_ok(seen):
    def _run(task, history=None, max_iters=None):
        seen["task"] = task
        seen["history"] = history
        seen["max_iters"] = max_iters
        try:
            seen["allow"] = list(agent_tools._ACTIVE_TOOL_ALLOW or [])
        except Exception:
            seen["allow"] = None
        return "child-done"
    return _run


# ---- slots ----

def test_slots_append_order(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    names = [t["name"] for t in agent_tools.TOOL_REGISTRY]
    assert names[15:18] == ["todo", "delegate_task", "exec_py"]
    assert names.index("todo") == 15  # slot 16 (1-based)
    assert names.index("delegate_task") == 16  # slot 17
    assert names.index("exec_py") == 17  # slot 18
    assert len(names) == 22
    assert agent_tools.all_tools_mask() == 0x3FFFFF


# ---- todo ----

def test_todo_crud(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert todo.handle({})["items"] == []
    r1 = todo.handle({"op": "add", "text": "read pin 4"})
    r2 = todo.handle({"op": "add", "text": "average it"})
    assert r1["success"] and r2["success"]
    assert (r1["item"]["id"], r2["item"]["id"]) == (1, 2)
    l = todo.handle({"op": "list"})
    assert l["count"] == 2 and l["max_items"] == 20
    assert [i["done"] for i in l["items"]] == [False, False]
    d = todo.handle({"op": "done", "id": 1})
    assert d["success"] and d["item"]["done"] is True
    assert todo.handle({"op": "list"})["items"][0]["done"] is True
    c = todo.handle({"op": "clear"})
    assert c["success"] and c["cleared"] == 2
    assert todo.handle({"op": "list"})["count"] == 0


def test_todo_bounds(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert todo.handle({"op": "add", "text": ""})["success"] is False
    assert todo.handle({"op": "add", "text": "x" * 200})["success"] is True
    assert todo.handle({"op": "add", "text": "x" * 201})["success"] is False
    todo._reset()
    for i in range(20):
        assert todo.handle({"op": "add", "text": "item %d" % i})["success"]
    r = todo.handle({"op": "add", "text": "one too many"})
    assert r["success"] is False and "full" in r["error"]
    assert todo.handle({"op": "done", "id": 999})["success"] is False
    assert todo.handle({"op": "done"})["success"] is False  # id required
    assert todo.handle({"op": "bogus"})["success"] is False
    assert todo.handle("not-a-dict")["success"] is True  # never raises
    # tool dispatch path
    s = agent_tools.execTool("todo", {"op": "list"})
    assert json.loads(s)["count"] == 20


# ---- delegate: success + restriction ----

def test_delegate_success_restriction_active(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = {}
    monkeypatch.setattr(agent_core, "runTurn", _fake_ok(seen))
    s = agent_tools.execTool("delegate_task", {"task": "read pin twice"})
    d = json.loads(s)
    assert d["exit"] == "completed" and d["result"] == "child-done"
    assert d["truncated"] is False
    assert seen["task"] == "read pin twice" and seen["history"] == []
    assert seen["max_iters"] == 3  # min(10, parent budget 3)
    all_names = [t["name"] for t in agent_tools.TOOL_REGISTRY]
    expect = [n for n in all_names
              if n not in ("restart_device", "gpio_write",
                           "delegate_task", "exec_py")]
    assert seen["allow"] == expect
    # restriction object restored after the child
    assert agent_tools._ACTIVE_TOOL_ALLOW is None


def test_delegate_child_sees_restriction(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = {}

    def _spy(task, history=None, max_iters=None):
        seen["allow"] = list(agent_tools._ACTIVE_TOOL_ALLOW or [])
        seen["ok"] = agent_tools.execTool("todo", {"op": "list"})
        seen["no"] = agent_tools.execTool("gpio_write",
                                          {"pin": 2, "level": 1})
        return "spy-done"

    monkeypatch.setattr(agent_core, "runTurn", _spy)
    d = json.loads(agent_tools.execTool("delegate_task", {"task": "spy"}))
    assert d["exit"] == "completed"
    assert json.loads(seen["ok"])["success"] is True  # allowed tool runs
    assert "not allowed" in seen["no"]  # default-excluded tool refused
    assert "gpio_write" not in seen["allow"]


def test_delegate_child_budget_capped(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = {}
    monkeypatch.setattr(agent_core, "runTurn", _fake_ok(seen))
    config.agent_max_iters = 5
    agent_tools.execTool("delegate_task", {"task": "x"})
    assert seen["max_iters"] == 5  # min(10, 5)
    config.agent_max_iters = 3


def test_delegate_tools_allow_narrows(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = {}
    monkeypatch.setattr(agent_core, "runTurn", _fake_ok(seen))
    d = json.loads(agent_tools.execTool(
        "delegate_task", {"task": "x", "tools_allow": ["todo"]}))
    assert d["exit"] == "completed" and seen["allow"] == ["todo"]
    # explicit listing re-allows gpio_write, but never restart_device
    d2 = json.loads(agent_tools.execTool(
        "delegate_task", {"task": "x",
                          "tools_allow": ["todo", "gpio_write",
                                          "restart_device"]}))
    assert d2["exit"] == "completed"
    delegate._reset()
    assert "gpio_write" in seen["allow"]
    assert "restart_device" not in seen["allow"]
    # tools_allow can never ADD beyond parent-enabled
    config.gToolsMask &= ~(1 << agent_tools.toolIndex("todo"))
    d3 = json.loads(agent_tools.execTool(
        "delegate_task", {"task": "x", "tools_allow": ["todo"]}))
    assert d3["exit"] == "completed" and seen["allow"] == []


def test_delegate_restart_never_in_child(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    seen = {}

    def _spy(task, history=None, max_iters=None):
        seen["allow"] = list(agent_tools._ACTIVE_TOOL_ALLOW or [])
        seen["r"] = agent_tools.execTool("restart_device", {})
        return "spy-done"

    monkeypatch.setattr(agent_core, "runTurn", _spy)
    d = json.loads(agent_tools.execTool(
        "delegate_task", {"task": "x",
                          "tools_allow": ["restart_device", "todo"]}))
    assert d["exit"] == "completed"
    assert "restart_device" not in seen["allow"]
    assert "not allowed" in seen["r"]


def test_delegate_nesting_refused(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def _spy(task, history=None, max_iters=None):
        inner = agent_tools.execTool("delegate_task", {"task": "nested"})
        return "outer saw: " + inner

    monkeypatch.setattr(agent_core, "runTurn", _spy)
    d = json.loads(agent_tools.execTool(
        "delegate_task", {"task": "outer",
                          "tools_allow": ["todo", "delegate_task"]}))
    assert d["exit"] == "completed" and "nesting" in d["result"]
    assert delegate._in_child is False  # flag restored
    # top-level delegation still works afterwards (one child used)
    monkeypatch.setattr(agent_core, "runTurn", _fake_ok({}))
    d2 = json.loads(agent_tools.execTool("delegate_task", {"task": "next"}))
    assert d2["exit"] == "completed"


def test_delegate_max_two_then_reset_next_turn(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    _orig_runturn = agent_core.runTurn
    seen = {}
    monkeypatch.setattr(agent_core, "runTurn", _fake_ok(seen))
    assert json.loads(agent_tools.execTool(
        "delegate_task", {"task": "a"}))["exit"] == "completed"
    assert json.loads(agent_tools.execTool(
        "delegate_task", {"task": "b"}))["exit"] == "completed"
    third = json.loads(agent_tools.execTool("delegate_task", {"task": "c"}))
    assert third["success"] is False and "at most 2" in third["error"]
    # next parent turn resets the counter via agent_core.runTurn
    monkeypatch.setattr(agent_core, "runTurn", _orig_runturn)
    monkeypatch.setattr(llm, "callLLMWithTools", lambda *a, **k: "stub-ok")
    assert agent_core.runTurn("hi", [], None) == "stub-ok"
    fourth = json.loads(agent_tools.execTool("delegate_task", {"task": "d"}))
    assert fourth["exit"] == "completed"


def test_delegate_child_exception_envelope(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def _boom(task, history=None, max_iters=None):
        raise RuntimeError("agent exploded")

    monkeypatch.setattr(agent_core, "runTurn", _boom)
    d = json.loads(agent_tools.execTool("delegate_task", {"task": "x"}))
    assert d["exit"] == "error" and d["success"] is False
    assert "exploded" in d["result"]
    # globals restored: no wedged toolset, no stuck depth flag
    assert agent_tools._ACTIVE_TOOL_ALLOW is None
    assert delegate._in_child is False
    monkeypatch.setattr(agent_core, "runTurn", _fake_ok({}))
    assert json.loads(agent_tools.execTool(
        "delegate_task", {"task": "y"}))["exit"] == "completed"


def test_delegate_exit_mapping_and_truncation(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    def _mk(reply):
        return lambda task, history=None, max_iters=None: reply

    monkeypatch.setattr(agent_core, "runTurn", _mk("ERROR: upstream down"))
    assert json.loads(agent_tools.execTool(
        "delegate_task", {"task": "x"}))["exit"] == "error"
    delegate._reset()
    monkeypatch.setattr(
        agent_core, "runTurn",
        _mk("Ran get_status (step budget reached before a summary). Results:\n.."))
    assert json.loads(agent_tools.execTool(
        "delegate_task", {"task": "x"}))["exit"] == "max_iterations"
    delegate._reset()
    monkeypatch.setattr(agent_core, "runTurn", _mk("Z" * 5000))
    d = json.loads(agent_tools.execTool("delegate_task", {"task": "x"}))
    assert d["exit"] == "completed" and len(d["result"]) == 1024
    assert d["truncated"] is True
    delegate._reset()
    assert json.loads(agent_tools.execTool(
        "delegate_task", {}))["success"] is False  # task required
    assert json.loads(agent_tools.execTool(
        "delegate_task",
        {"task": "x", "tools_allow": "todo"}))["success"] is False


# ---- exec_py ----

_BLOCKED_CASES = [
    "import machine\nmachine.Pin(2)",
    "import network",
    "import os",
    "import uos",
    "import sys",
    "from machine import Pin",
    "from network import WLAN",
    "from os import listdir",
    "x = __import__('os')",
    "f = open('x.txt')",
    "eval('1+1')",
    "exec('x=1')",
    "compile('1','','exec')",
    "import  os",  # spacing evasion
    "from\tmachine import Pin",  # tab evasion
]


def test_exec_blocklist_matrix(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    for code in _BLOCKED_CASES:
        r = exec_py.run_code(code)
        assert r["success"] is False, code
        assert "blocked" in r["error"], code
    # same verdict through tool dispatch
    s = agent_tools.execTool("exec_py", {"code": "import os"})
    assert "blocked" in json.loads(s)["error"]


def test_exec_output_and_caps(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    r = exec_py.run_code("x = 6 * 7")
    assert r["success"] is True and r["output"] == ""
    r = exec_py.run_code("print('hello')\nprint(40 + 2)")
    assert r["success"] is True and r["output"] == "hello\n42"
    assert r["truncated"] is False
    r = exec_py.run_code("s = 'abc'.upper()\nprint(s)")
    assert r["output"] == "ABC"
    r = exec_py.run_code("print('A' * 5000)")
    assert r["success"] is True and len(r["output"]) == 1024
    assert r["truncated"] is True
    r = exec_py.run_code("print(1 / 0)")
    assert r["success"] is False and "exec failed" in r["error"]
    r = exec_py.run_code("x = 1\n" * 400)  # 2400 chars > 2KB
    assert r["success"] is False and "too long" in r["error"]
    assert exec_py.run_code("")["success"] is False
    assert exec_py.run_code("   ")["success"] is False
    s = agent_tools.execTool("exec_py", {"code": "print(21 * 2)"})
    assert json.loads(s)["output"] == "42"


def test_exec_tool_default_off(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    assert exec_py.TOOL.get("default_off") is True
    assert agent_tools.toolIndex("exec_py") == 17


def test_exec_fresh_default_excludes(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    try:
        os.remove("config.json")
    except OSError:
        pass
    config.loadConfig()
    idx = agent_tools.toolIndex("exec_py")
    assert (config.gToolsMask >> idx) & 1 == 0  # exec_py off by default
    assert (config.gToolsMask >> agent_tools.toolIndex("todo")) & 1 == 1
    assert (config.gToolsMask >> agent_tools.toolIndex("delegate_task")) & 1 == 1
    assert config.gToolsMask == 0x3DFFFF  # all 22 on except exec_py


def test_exec_explicit_enable_survives_reload(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config.saveToolsMask(0x3FFFFF)  # user deliberately enables everything
    config.loadConfig()
    assert (config.gToolsMask >> agent_tools.toolIndex("exec_py")) & 1 == 1


def test_exec_old_stored_mask_no_gain(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config.saveToolsMask(0x7FFF)  # old 15-tool "all on" stored on flash
    config.loadConfig()
    assert config.gToolsMask == 0x3DFFFF  # gains todo+delegate+file tools, NOT exec_py
    assert (config.gToolsMask >> agent_tools.toolIndex("exec_py")) & 1 == 0


# ---- restriction primitive ----

def test_restriction_filters_dispatch_and_prompt(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    agent_tools._ACTIVE_TOOL_ALLOW = ["todo"]
    try:
        assert json.loads(agent_tools.execTool(
            "todo", {"op": "list"}))["success"] is True
        assert "not allowed" in agent_tools.execTool("gpio_read", {})
        req = {}
        agent_tools.addToolsArray(req)
        got = sorted(t["function"]["name"] for t in req["tools"])
        assert got == ["todo"]
    finally:
        agent_tools._ACTIVE_TOOL_ALLOW = None
    req2 = {}
    agent_tools.addToolsArray(req2)
    assert len(req2["tools"]) == 22  # unrestricted parent sees everything


# ---- micropython portability ----

def test_no_regex_or_bad_codecs_in_new_code():
    base = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("todo.py", "delegate.py", "exec_py.py", "agent_core.py",
                "agent_tools.py", "config.py"):
        src = open(os.path.join(base, rel), encoding="utf-8").read()
        assert "import re" not in src, "no `re` in %s" % rel
        for codec in ("iso-8859-1", "latin-1", "cp1252", "utf-16"):
            assert codec not in src, "unsupported codec in %s" % rel
