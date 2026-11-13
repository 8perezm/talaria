# test_run_script.py - the run_script tool and its executor.
#
# The tool is a thin wrapper over cron.run_script_file(), so these cover both:
# the JSON contract the model sees, and that a workspace .py file really runs.
import json
import os
import sys
import types

import cron
import tools.tool_run_script as tool


def _fake_cron(monkeypatch, result):
    mod = types.ModuleType("cron")
    mod.run_script_file = lambda path: result
    monkeypatch.setitem(sys.modules, "cron", mod)


def test_tool_returns_stdout(monkeypatch):
    _fake_cron(monkeypatch, (True, "hello from script"))
    out = json.loads(tool.TOOL["run"]({"path": "hello.py"}))
    assert out == {"success": True, "path": "hello.py",
                   "output": "hello from script"}


def test_tool_reports_executor_error(monkeypatch):
    _fake_cron(monkeypatch, (False, "exec failed: NameError: x"))
    out = json.loads(tool.TOOL["run"]({"path": "broken.py"}))
    assert out["success"] is False
    assert "NameError" in out["error"]


def test_tool_requires_path(monkeypatch):
    out = json.loads(tool.TOOL["run"]({}))
    assert out["success"] is False
    assert "path" in out["error"]


def test_rejects_paths_outside_workspace():
    ok, err = cron.run_script_file("opt/data/cron.json")
    assert ok is False
    assert "workspace" in err


def test_executes_a_workspace_script(tmp_path, monkeypatch):
    import fsutil
    # full() prefixes "/" when _FS_ROOT is empty, so point the tree at tmp
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    os.makedirs(os.path.join(str(tmp_path), "opt", "data", "workspace"),
                exist_ok=True)
    path = os.path.join(str(tmp_path), "opt", "data", "workspace", "hello.py")
    with open(path, "w") as f:
        f.write("print('hi from the device workspace')\n")

    ok, out = cron.run_script_file("hello.py")
    assert ok is True
    assert "hi from the device workspace" in out


def test_missing_script_fails_cleanly(tmp_path, monkeypatch):
    import fsutil
    monkeypatch.setattr(fsutil, "_FS_ROOT", str(tmp_path).replace("\\", "/"))
    ok, err = cron.run_script_file("does-not-exist.py")
    assert ok is False
    assert isinstance(err, str) and err
